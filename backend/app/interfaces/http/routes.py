from __future__ import annotations

from fastapi import APIRouter

from app.interfaces.http import cases, diagnostics, evals, export, maintenance, review, settings

router = APIRouter()
router.include_router(cases.router)
router.include_router(diagnostics.router)
router.include_router(review.router)
router.include_router(export.router)
router.include_router(evals.router)
router.include_router(settings.router)
router.include_router(maintenance.router)
