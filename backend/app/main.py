from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.database import init_db
from app.core.settings import settings


def create_app() -> FastAPI:
    init_db()
    app = FastAPI(title=settings.app_name)

    @app.middleware("http")
    async def local_access_guard(request: Request, call_next):
        if _request_is_allowed(request):
            return await call_next(request)
        return JSONResponse(
            status_code=403,
            content={"detail": "Remote access is disabled. Start EYEX on loopback or set EYEX_ALLOW_REMOTE_ACCESS with a bearer token."},
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix="/api")
    return app


app = create_app()


def _request_is_allowed(request: Request) -> bool:
    client_host = request.client.host if request.client else None
    if not _host_is_loopback(client_host):
        return _remote_access_authorized(request)

    for header_name in ("origin", "referer"):
        header_value = request.headers.get(header_name)
        if not header_value:
            continue
        header_host = urlparse(header_value).hostname
        if header_host and not _host_is_loopback(header_host):
            return _remote_access_authorized(request)
    return True


def _remote_access_authorized(request: Request) -> bool:
    if not settings.allow_remote_access or not settings.local_api_token:
        return False
    expected = f"Bearer {settings.local_api_token}"
    return request.headers.get("authorization") == expected


def _host_is_loopback(host: str | None) -> bool:
    if not host:
        return True
    normalized = host.strip().strip("[]").lower()
    if normalized in {"localhost", "testclient"}:
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False
