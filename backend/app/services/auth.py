from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, Request, status

from app.core.config import settings


@dataclass(frozen=True)
class AuthUser:
    sub: str
    email: str | None = None
    name: str | None = None


def oauth_configuration_status() -> dict[str, Any]:
    provider = settings.oauth_provider
    missing: list[str] = []
    if settings.oauth_enabled and provider == "oidc":
        required = {
            "EYES_OAUTH_CLIENT_ID": settings.oauth_client_id,
            "EYES_OAUTH_AUTHORIZATION_URL": settings.oauth_authorization_url,
            "EYES_OAUTH_TOKEN_URL": settings.oauth_token_url,
            "EYES_OAUTH_USERINFO_URL": settings.oauth_userinfo_url,
        }
        missing = [key for key, value in required.items() if not value]

    warnings: list[str] = []
    if settings.oauth_enabled and settings.oauth_session_secret == "change-me-for-production":
        warnings.append("EYES_OAUTH_SESSION_SECRET is using the default development value")

    return {
        "auth_provider": provider,
        "configured": not missing,
        "missing_config": missing,
        "config_warnings": warnings,
        "chatgpt_login_available": settings.oauth_enabled and provider == "chatgpt",
    }


def auth_status_from_request(request: Request) -> dict[str, Any]:
    model_auth = model_auth_status()
    if not settings.oauth_enabled:
        return {
            "enabled": False,
            "auth_provider": settings.oauth_provider,
            "configured": True,
            "missing_config": [],
            "config_warnings": [],
            "chatgpt_login_available": False,
            "authenticated": True,
            "user": {"sub": "local-dev"},
            "model_auth": model_auth,
        }
    config_status = oauth_configuration_status()
    user = current_user_from_request(request)
    return {
        "enabled": True,
        **config_status,
        "authenticated": user is not None,
        "user": None if user is None else user.__dict__,
        "model_auth": model_auth,
    }


def model_auth_status() -> dict[str, Any]:
    api_key_configured = bool(settings.openai_api_key)
    try:
        from app.services.chatgpt_token_store import has_chatgpt_model_auth

        chatgpt_codex_configured = has_chatgpt_model_auth()
    except Exception:
        chatgpt_codex_configured = False

    auth_mode = settings.openai_auth_mode
    provider = "local_fallback"
    online_model_available = False
    if auth_mode != "disabled":
        if auth_mode in {"auto", "api_key"} and api_key_configured:
            provider = "openai_api_key"
            online_model_available = True
        elif auth_mode in {"auto", "chatgpt"} and chatgpt_codex_configured:
            provider = "chatgpt_codex"
            online_model_available = True

    return {
        "auth_mode": auth_mode,
        "provider": provider,
        "online_model_available": online_model_available,
        "api_key_configured": api_key_configured,
        "chatgpt_codex_configured": chatgpt_codex_configured,
    }


def require_user(request: Request) -> AuthUser:
    if not settings.oauth_enabled:
        return AuthUser(sub="local-dev", email="local-dev@localhost", name="Local Dev")
    user = current_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return user


def current_user_from_request(request: Request) -> AuthUser | None:
    token = request.cookies.get(settings.oauth_session_cookie)
    if not token:
        return None
    payload = verify_signed_payload(token, max_age_seconds=settings.oauth_session_ttl_seconds)
    if not payload:
        return None
    return AuthUser(
        sub=str(payload.get("sub") or payload.get("email") or "unknown"),
        email=payload.get("email"),
        name=payload.get("name"),
    )


def build_authorization_redirect(next_path: str = "/") -> tuple[str, str]:
    if not settings.oauth_enabled:
        raise HTTPException(status_code=400, detail="OAuth is not enabled")
    if settings.oauth_provider == "chatgpt":
        from app.services.chatgpt_oauth import begin_chatgpt_login

        return begin_chatgpt_login(next_path), ""
    _require_oauth_configuration()

    state_payload = {
        "nonce": secrets.token_urlsafe(24),
        "next": _safe_next_path(next_path),
    }
    signed_state = sign_payload(state_payload)
    query = urlencode(
        {
            "client_id": settings.oauth_client_id,
            "redirect_uri": settings.oauth_redirect_uri,
            "response_type": "code",
            "scope": settings.oauth_scopes,
            "state": signed_state,
        }
    )
    return f"{settings.oauth_authorization_url}?{query}", signed_state


async def exchange_code_for_user(code: str, state: str, state_cookie: str | None) -> tuple[AuthUser, str]:
    if not state_cookie or not hmac.compare_digest(state, state_cookie):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    state_payload = verify_signed_payload(state_cookie, max_age_seconds=600)
    if state_payload is None:
        raise HTTPException(status_code=400, detail="Expired OAuth state")
    _require_oauth_configuration()

    async with httpx.AsyncClient(timeout=15) as client:
        token_response = await client.post(
            settings.oauth_token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.oauth_redirect_uri,
                "client_id": settings.oauth_client_id,
                "client_secret": settings.oauth_client_secret or "",
            },
            headers={"Accept": "application/json"},
        )
        token_response.raise_for_status()
        token_payload = token_response.json()
        access_token = token_payload.get("access_token")
        if not access_token:
            raise HTTPException(status_code=400, detail="OAuth provider did not return access_token")

        userinfo_response = await client.get(
            settings.oauth_userinfo_url,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        userinfo_response.raise_for_status()
        userinfo = userinfo_response.json()

    user = AuthUser(
        sub=str(userinfo.get("sub") or userinfo.get("id") or userinfo.get("email") or ""),
        email=userinfo.get("email"),
        name=userinfo.get("name") or userinfo.get("preferred_username"),
    )
    if not user.sub:
        raise HTTPException(status_code=400, detail="OAuth userinfo did not include subject")
    _enforce_allowed_domain(user.email)
    return user, _safe_next_path(str(state_payload.get("next") or "/"))


def create_session_cookie(user: dict[str, Any] | AuthUser) -> str:
    payload = user.__dict__ if isinstance(user, AuthUser) else dict(user)
    payload["iat"] = int(time.time())
    return sign_payload(payload)


def sign_payload(payload: dict[str, Any]) -> str:
    payload = dict(payload)
    payload.setdefault("iat", int(time.time()))
    body = _b64(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    signature = _signature(body)
    return f"{body}.{signature}"


def verify_signed_payload(token: str, *, max_age_seconds: int) -> dict[str, Any] | None:
    try:
        body, signature = token.rsplit(".", 1)
    except ValueError:
        return None
    if not hmac.compare_digest(signature, _signature(body)):
        return None
    try:
        payload = json.loads(_b64decode(body))
    except (ValueError, json.JSONDecodeError):
        return None
    issued_at = int(payload.get("iat", 0))
    if issued_at and time.time() - issued_at > max_age_seconds:
        return None
    return payload


def _signature(body: str) -> str:
    secret = settings.oauth_session_secret.encode("utf-8")
    digest = hmac.new(secret, body.encode("utf-8"), hashlib.sha256).digest()
    return _b64(digest)


def _b64(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _b64decode(payload: str) -> bytes:
    padded = payload + "=" * (-len(payload) % 4)
    return base64.urlsafe_b64decode(padded)


def _safe_next_path(next_path: str) -> str:
    if not next_path.startswith("/") or next_path.startswith("//"):
        return "/"
    return next_path


def _enforce_allowed_domain(email: str | None) -> None:
    allowed = [domain.strip().lower() for domain in settings.oauth_allowed_email_domains.split(",") if domain.strip()]
    if not allowed:
        return
    if not email or "@" not in email:
        raise HTTPException(status_code=403, detail="Email domain is required")
    domain = email.rsplit("@", 1)[1].lower()
    if domain not in allowed:
        raise HTTPException(status_code=403, detail="Email domain is not allowed")


def _require_oauth_configuration() -> None:
    config_status = oauth_configuration_status()
    if config_status["configured"]:
        return
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "error": "OAuth is enabled but not fully configured",
            "missing_config": config_status["missing_config"],
            "config_warnings": config_status["config_warnings"],
        },
    )
