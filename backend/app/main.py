from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.application.errors import ApplicationError
from app.core.config import settings
from app.infrastructure.db.session import init_db
from app.infrastructure.storage.files import ensure_storage_dirs
from app.interfaces.http.auth import router as auth_router
from app.interfaces.http.routes import router


def create_app() -> FastAPI:
    ensure_storage_dirs()
    init_db()
    app = FastAPI(title=settings.app_name)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth_router)
    app.include_router(router)

    @app.exception_handler(ApplicationError)
    async def application_error_handler(_, exc: ApplicationError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def value_error_handler(_, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return app


app = create_app()
