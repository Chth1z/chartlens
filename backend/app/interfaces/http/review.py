from __future__ import annotations

from fastapi import APIRouter, Depends

from app.application.ports import CaseRepository
from app.application.review import ReviewField
from app.composition.dependencies import get_case_repository
from app.domain.auth import AuthUser
from app.domain.clinical import ReviewUpdate
from app.interfaces.http.auth_service import require_user

router = APIRouter(prefix="/api")


@router.patch("/cases/{case_id}/review")
def update_review(
    case_id: str,
    update: ReviewUpdate,
    _: AuthUser = Depends(require_user),
    repository: CaseRepository = Depends(get_case_repository),
) -> dict:
    return ReviewField(repository).execute(case_id, update)
