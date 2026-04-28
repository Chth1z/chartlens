from __future__ import annotations

from fastapi import APIRouter, Depends

from app.application.evals import RunEval
from app.application.ports import CaseRepository
from app.composition.dependencies import get_case_repository
from app.domain.auth import AuthUser
from app.domain.clinical import EvalRunRequest
from app.interfaces.http.auth_service import require_user

router = APIRouter(prefix="/api")


@router.post("/evals/runs", status_code=201)
def create_eval_run(
    request: EvalRunRequest,
    _: AuthUser = Depends(require_user),
    repository: CaseRepository = Depends(get_case_repository),
) -> dict:
    return RunEval(repository).execute(request)
