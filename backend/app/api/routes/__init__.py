"""Public router for the EYEX backend API.

The API is split into focused modules by concern (health, models, cases,
diagnostics, system, evaluations). This module assembles them into a single
``APIRouter`` so callers can still do ``from app.api.routes import router``.
"""

from __future__ import annotations

from fastapi import APIRouter

from .analytics import router as analytics_router
from .cases import router as cases_router
from .diagnostics import router as diagnostics_router
from .evaluations import router as evaluations_router
from .health import router as health_router
from .models import router as models_router
from .system import router as system_router

# Backward-compatible re-export. `backend/tests/test_api_smoke.py` imports
# `_pdf_source_render_scale` from `app.api.routes`; the helper now lives in
# `_helpers` but the public name is preserved.
from ._helpers import _pdf_source_render_scale  # noqa: F401

router = APIRouter()
router.include_router(health_router)
router.include_router(models_router)
router.include_router(cases_router)
router.include_router(diagnostics_router)
router.include_router(system_router)
router.include_router(evaluations_router)
router.include_router(analytics_router)

__all__ = ["router"]
