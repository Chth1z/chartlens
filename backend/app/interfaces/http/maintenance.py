from __future__ import annotations

from fastapi import APIRouter, Depends

from app.application.maintenance import ClearAllCases, ClearProcessingCache
from app.application.ports import MaintenancePort
from app.composition.dependencies import get_maintenance
from app.domain.auth import AuthUser
from app.interfaces.http.auth_service import require_user

router = APIRouter(prefix="/api/maintenance")


@router.post("/clear-cache")
def clear_cache(
    _: AuthUser = Depends(require_user),
    maintenance: MaintenancePort = Depends(get_maintenance),
) -> dict:
    affected = ClearProcessingCache(maintenance).execute()
    return {"ok": True, "affected_count": affected, "message": "Processing cache cleared"}


@router.post("/clear-all-cases")
def clear_cases(
    _: AuthUser = Depends(require_user),
    maintenance: MaintenancePort = Depends(get_maintenance),
) -> dict:
    affected = ClearAllCases(maintenance).execute()
    return {"ok": True, "affected_count": affected, "message": "All case records cleared"}
