"""Per-case diagnostics route."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.contracts import CaseDiagnosticsResponse
from app.core.database import get_db
from app.services.diagnostics import build_case_diagnostics

from ._helpers import _require_case


router = APIRouter()


@router.get("/cases/{case_id}/diagnostics", response_model=CaseDiagnosticsResponse)
def diagnostics(case_id: str, db: Annotated[Session, Depends(get_db)]) -> dict:
    case = _require_case(db, case_id)
    return build_case_diagnostics(case)
