"""Evaluation routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.contracts import BatchEvaluationResponse, EvaluationProfileRunResponse
from app.core.config_loader import load_evaluation_profile
from app.core.database import get_db
from app.domain.models import EvaluationRequest, EvaluationResult
from app.services.extraction_eval import (
    evaluate_case_against_gold,
    run_extraction_evaluation,
    summarize_eval_cases,
)

from ._helpers import _require_case


router = APIRouter()


class BatchEvaluationCasePayload(BaseModel):
    case_id: str
    gold: dict[str, str]


class BatchEvaluationPayload(BaseModel):
    cases: list[BatchEvaluationCasePayload]


@router.post("/evals/runs", response_model=EvaluationResult)
def run_eval(request: EvaluationRequest, db: Annotated[Session, Depends(get_db)]) -> EvaluationResult:
    _require_case(db, request.case_id)
    case_payload = evaluate_case_against_gold(request.case_id, request.gold, db)
    evidence_failures = [
        field["field_key"]
        for field in case_payload["fields"]
        if field["actual"] not in (None, "unknown") and not field["has_evidence"]
    ]
    unknown_count = sum(1 for field in case_payload["fields"] if field["actual"] in (None, "unknown"))
    return EvaluationResult(
        case_id=request.case_id,
        total=case_payload["total_fields"],
        correct=case_payload["correct"],
        accuracy=case_payload["accuracy"],
        unknown_count=unknown_count,
        missing_evidence_failures=evidence_failures,
    )


@router.post("/evals/batch", response_model=BatchEvaluationResponse)
def run_batch_eval(request: BatchEvaluationPayload, db: Annotated[Session, Depends(get_db)]) -> dict:
    case_results = [evaluate_case_against_gold(item.case_id, item.gold, db) for item in request.cases]
    summary = summarize_eval_cases(case_results)
    return {"summary": summary, "cases": case_results}


@router.post("/evals/profiles/{profile_id}/run", response_model=EvaluationProfileRunResponse)
def run_evaluation_profile(profile_id: str, db: Annotated[Session, Depends(get_db)]) -> dict:
    try:
        profile = load_evaluation_profile(profile_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Evaluation profile not found") from None
    report = run_extraction_evaluation(profile, db=db)
    return {
        "profile": report["profile"],
        "summary": report["summary"],
        "cases": report["cases"],
    }
