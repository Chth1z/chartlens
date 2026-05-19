from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.database import init_db
from app.core.settings import settings


def _request_header_host(request: Request, header_name: str) -> str | None:
    header_value = request.headers.get(header_name)
    if not header_value:
        return None
    return urlparse(header_value).hostname


def _request_origin_host(request: Request) -> str | None:
    for header_name in ("origin", "referer"):
        header_host = _request_header_host(request, header_name)
        if header_host:
            return header_host
    return None


def _request_is_allowed(request: Request) -> bool:
    if request.method == "OPTIONS":
        origin_host = _request_origin_host(request)
        if origin_host and not _host_is_loopback(origin_host):
            return bool(settings.allow_remote_access and settings.local_api_token)

    client_host = request.client.host if request.client else None
    if not _host_is_loopback(client_host):
        return _remote_access_authorized(request)

    origin_host = _request_origin_host(request)
    if origin_host and not _host_is_loopback(origin_host):
        return _remote_access_authorized(request)
    return True


def _remote_access_authorized(request: Request) -> bool:
    if not settings.allow_remote_access or not settings.local_api_token:
        return False
    expected = f"Bearer {settings.local_api_token}"
    return request.headers.get("authorization") == expected


def _cors_allow_origins() -> list[str]:
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ]


def _cors_allow_origin_regex() -> str | None:
    if settings.allow_remote_access and settings.local_api_token:
        return r"^https?://[^/]+$"
    return None


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


def create_app() -> FastAPI:
    init_db()

    from app.core.logging import init_logging
    init_logging()

    from app.core.telemetry import init_telemetry
    init_telemetry()

    from app.services.recovery import recover_abandoned_runs
    recover_abandoned_runs()

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
        allow_origins=_cors_allow_origins(),
        allow_origin_regex=_cors_allow_origin_regex(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix="/api")
    return app


app = create_app()
