from __future__ import annotations

from fastapi import APIRouter, Depends

from app.application.diagnostics import GetDiagnostics, RequestVisionFallback
from app.application.ports import CaseRepository, SystemConfigProvider
from app.composition.dependencies import get_case_repository, get_system_config_provider
from app.domain.auth import AuthUser
from app.domain.clinical import VisionFallbackRequest
from app.interfaces.http.auth_service import require_user

router = APIRouter(prefix="/api")


@router.get("/cases/{case_id}/diagnostics")
def case_diagnostics(
    case_id: str,
    _: AuthUser = Depends(require_user),
    repository: CaseRepository = Depends(get_case_repository),
    config_provider: SystemConfigProvider = Depends(get_system_config_provider),
) -> dict:
    return GetDiagnostics(repository=repository, config_provider=config_provider).execute(case_id)


@router.post("/cases/{case_id}/vision-fallback-requests", status_code=201)
def create_vision_fallback_request(
    case_id: str,
    request: VisionFallbackRequest,
    _: AuthUser = Depends(require_user),
    repository: CaseRepository = Depends(get_case_repository),
    config_provider: SystemConfigProvider = Depends(get_system_config_provider),
) -> dict:
    return RequestVisionFallback(repository=repository, config_provider=config_provider).execute(case_id, request)
