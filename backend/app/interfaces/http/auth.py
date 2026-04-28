from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.interfaces.http.auth_service import (
    AuthUser,
    auth_status_from_request,
    build_authorization_redirect,
    create_session_cookie,
    current_user_from_request,
    exchange_code_for_user,
    require_user,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me")
def me(request: Request) -> dict:
    return auth_status_from_request(request)


@router.get("/login")
def login(next: str = Query(default="/")) -> RedirectResponse:
    location, state = build_authorization_redirect(next)
    response = RedirectResponse(location)
    if state:
        response.set_cookie(
            settings.oauth_state_cookie,
            state,
            max_age=600,
            httponly=True,
            samesite="lax",
        )
    return response


@router.get("/callback")
async def callback(request: Request, code: str, state: str) -> RedirectResponse:
    user, next_path = await exchange_code_for_user(
        code=code,
        state=state,
        state_cookie=request.cookies.get(settings.oauth_state_cookie),
    )
    response = RedirectResponse(next_path)
    response.set_cookie(
        settings.oauth_session_cookie,
        create_session_cookie(user),
        max_age=settings.oauth_session_ttl_seconds,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(settings.oauth_state_cookie)
    return response


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(settings.oauth_session_cookie)
    response.delete_cookie(settings.oauth_state_cookie)
    _clear_chatgpt_model_tokens()
    return {"ok": True}


@router.get("/logout")
def logout_redirect() -> RedirectResponse:
    response = RedirectResponse("/")
    response.delete_cookie(settings.oauth_session_cookie)
    response.delete_cookie(settings.oauth_state_cookie)
    _clear_chatgpt_model_tokens()
    return response


@router.delete("/model-token")
def delete_model_token(_: AuthUser = Depends(require_user)) -> dict:
    from app.infrastructure.auth.chatgpt_token_store import clear_chatgpt_tokens

    removed = clear_chatgpt_tokens()
    return {
        "ok": True,
        "affected_count": 1 if removed else 0,
        "message": "ChatGPT/Codex model token cache cleared" if removed else "No ChatGPT/Codex model token cache found",
    }


@router.get("/chatgpt/complete")
def complete_chatgpt_login(ticket: str, request: Request, response: Response) -> dict:
    from app.infrastructure.auth.chatgpt_oauth import complete_chatgpt_ticket

    completed = complete_chatgpt_ticket(ticket)
    if completed is None:
        existing_user = current_user_from_request(request)
        if existing_user is not None:
            return {"ok": True, "next": "/", "user": existing_user.__dict__}
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Invalid or expired ChatGPT login ticket")
    user, next_path = completed
    response.set_cookie(
        settings.oauth_session_cookie,
        create_session_cookie(user),
        max_age=settings.oauth_session_ttl_seconds,
        httponly=True,
        samesite="lax",
    )
    return {"ok": True, "next": next_path, "user": user.__dict__}


def _clear_chatgpt_model_tokens() -> None:
    if settings.oauth_provider != "chatgpt":
        return
    from app.infrastructure.auth.chatgpt_token_store import clear_chatgpt_tokens

    clear_chatgpt_tokens()
