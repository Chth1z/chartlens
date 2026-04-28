from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.core.config import settings
from app.core.database import get_db
from app.schemas.pipeline import EvalRunRequest, FieldExtractionResult, ReviewUpdate, VisionFallbackRequest
from app.services.auth import AuthUser, require_user
from app.services.exporter import build_excel_workbook
from app.services.field_dictionary import load_field_dictionary
from app.services.pipeline import process_case
from app.services.storage import save_upload
from app.services.system_config import load_system_config
from app.services.task_queue import submit_case_processing

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/field-dictionary")
def field_dictionary() -> dict:
    return load_field_dictionary().model_dump()


@router.get("/cases")
def list_cases(_: AuthUser = Depends(require_user), db: Session = Depends(get_db)) -> list[dict]:
    records = db.scalars(select(models.CaseRecord).order_by(models.CaseRecord.created_at.desc())).all()
    return [_case_payload(db, record) for record in records]


@router.post("/cases", status_code=201)
async def create_case(
    file: UploadFile = File(...),
    _: AuthUser = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    file_hash, path, payload = await save_upload(file)
    existing_case = db.scalar(select(models.CaseRecord).where(models.CaseRecord.file_hash == file_hash).limit(1))
    suffix = "-DUP" if existing_case else ""
    case_id = f"CASE-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:8].upper()}{suffix}"

    record = models.CaseRecord(
        case_id=case_id,
        filename=file.filename or path.name,
        file_hash=file_hash,
        file_path=str(path),
        status="queued",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    if settings.sync_pipeline:
        process_case(db=db, case=record, payload=payload)
    else:
        submit_case_processing(record.case_id)
    return _case_payload(db, record)


@router.get("/cases/{case_id}")
def get_case(case_id: str, _: AuthUser = Depends(require_user), db: Session = Depends(get_db)) -> dict:
    record = _get_case_or_404(db, case_id)
    return _case_payload(db, record)


@router.get("/cases/{case_id}/diagnostics")
def case_diagnostics(case_id: str, _: AuthUser = Depends(require_user), db: Session = Depends(get_db)) -> dict:
    record = _get_case_or_404(db, case_id)
    runs = db.scalars(
        select(models.ProcessingRunRecord)
        .where(models.ProcessingRunRecord.case_id == case_id)
        .order_by(models.ProcessingRunRecord.created_at.desc())
    ).all()
    fragments = db.scalars(
        select(models.DocumentFragmentRecord)
        .where(models.DocumentFragmentRecord.case_id == case_id)
        .order_by(models.DocumentFragmentRecord.page, models.DocumentFragmentRecord.reading_order)
    ).all()
    model_calls = db.scalars(
        select(models.ModelCallLogRecord)
        .where(models.ModelCallLogRecord.case_id == case_id)
        .order_by(models.ModelCallLogRecord.created_at.desc())
    ).all()
    vision_requests = db.scalars(
        select(models.VisionFallbackRequestRecord)
        .where(models.VisionFallbackRequestRecord.case_id == case_id)
        .order_by(models.VisionFallbackRequestRecord.created_at.desc())
    ).all()
    config = load_system_config()
    latest_run = runs[0] if runs else None
    return {
        "case_id": record.case_id,
        "quality": _quality_payload(latest_run),
        "latest_run": _run_payload(latest_run) if latest_run else None,
        "run_count": len(runs),
        "runs": [_run_payload(run) for run in runs[:10]],
        "fragments": [_fragment_payload(fragment) for fragment in fragments if fragment.block_type != "line"][:300],
        "model_calls": [_model_call_payload(call) for call in model_calls[:50]],
        "vision_requests": [_vision_request_payload(item) for item in vision_requests[:50]],
        "config": {
            "ocr_default_profile": config.ocr.default_profile,
            "layout_default_profile": config.layout.default_profile,
            "llm_default_profile": config.llm.default_profile,
            "vision_fallback_enabled": config.llm.vision_fallback.enabled,
            "vision_fallback_requires_manual_approval": config.llm.vision_fallback.requires_manual_approval,
            "gold_sample_target_min": config.evaluation.gold_sample_target_min,
        },
    }


@router.post("/cases/{case_id}/reprocess")
def reprocess_case(case_id: str, _: AuthUser = Depends(require_user), db: Session = Depends(get_db)) -> dict:
    record = _get_case_or_404(db, case_id)
    path = Path(record.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Original case file is missing")
    record.status = "queued"
    record.error_message = None
    db.commit()
    if settings.sync_pipeline:
        payload = path.read_bytes()
        process_case(db=db, case=record, payload=payload)
        db.refresh(record)
    else:
        submit_case_processing(record.case_id)
    return _case_payload(db, record)


@router.post("/cases/{case_id}/vision-fallback-requests", status_code=201)
def create_vision_fallback_request(
    case_id: str,
    request: VisionFallbackRequest,
    _: AuthUser = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    _get_case_or_404(db, case_id)
    config = load_system_config()
    if not config.llm.vision_fallback.enabled:
        raise HTTPException(status_code=400, detail="Vision fallback is disabled")
    if config.llm.vision_fallback.requires_manual_approval and not request.manual_redaction_confirmed:
        raise HTTPException(status_code=400, detail="Manual redaction confirmation is required")
    record = models.VisionFallbackRequestRecord(
        request_id=f"VFR-{uuid4().hex[:12].upper()}",
        case_id=case_id,
        page=request.page,
        bbox=request.bbox,
        status="approved_pending",
        reason=request.reason,
        reviewer=request.reviewer,
        approved_at=datetime.now(UTC),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return _vision_request_payload(record)


@router.patch("/cases/{case_id}/review")
def update_review(
    case_id: str,
    update: ReviewUpdate,
    _: AuthUser = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    _get_case_or_404(db, case_id)
    result = db.scalar(
        select(models.ExtractionResultRecord).where(
            models.ExtractionResultRecord.case_id == case_id,
            models.ExtractionResultRecord.field_key == update.field_key,
        )
    )
    if result is None:
        result = models.ExtractionResultRecord(case_id=case_id, field_key=update.field_key)
        db.add(result)
        db.flush()

    audit = models.ReviewAuditRecord(
        case_id=case_id,
        field_key=update.field_key,
        old_raw_value=result.raw_value,
        old_normalized_code=result.normalized_code,
        new_raw_value=update.new_raw_value,
        new_normalized_code=update.new_normalized_code,
        reviewer=update.reviewer,
        reason=update.reason,
    )
    db.add(audit)

    result.raw_value = update.new_raw_value
    result.normalized_code = update.new_normalized_code
    result.review_required = False
    result.confidence = 1.0
    result.error_code = None
    result.reasoning_summary = f"人工复核：{update.reason}"
    result.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(result)
    return _result_payload(result)


@router.get("/cases/{case_id}/export.xlsx")
def export_case(case_id: str, _: AuthUser = Depends(require_user), db: Session = Depends(get_db)) -> Response:
    _get_case_or_404(db, case_id)
    dictionary = load_field_dictionary()
    results = [
        FieldExtractionResult.model_validate(_result_payload(record))
        for record in db.scalars(
            select(models.ExtractionResultRecord).where(models.ExtractionResultRecord.case_id == case_id)
        ).all()
    ]
    content = build_excel_workbook(case_id, dictionary, results)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{case_id}.xlsx"'},
    )


@router.post("/evals/runs", status_code=201)
def create_eval_run(
    request: EvalRunRequest,
    _: AuthUser = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    total = 0
    exact = 0
    unknown = 0
    missing_cases: list[str] = []
    for item in request.cases:
        record = db.scalar(select(models.CaseRecord).where(models.CaseRecord.case_id == item.case_id))
        if record is None:
            missing_cases.append(item.case_id)
            continue
        results = {
            result.field_key: result
            for result in db.scalars(
                select(models.ExtractionResultRecord).where(models.ExtractionResultRecord.case_id == item.case_id)
            ).all()
        }
        for field_key, expected in item.expected_fields.items():
            total += 1
            actual = results.get(field_key)
            if actual is None or actual.normalized_code in (None, "unknown"):
                unknown += 1
            if actual is not None and str(actual.normalized_code) == str(expected):
                exact += 1
    metrics = {
        "total_fields": total,
        "exact_matches": exact,
        "accuracy": round(exact / total, 4) if total else 0.0,
        "unknown_rate": round(unknown / total, 4) if total else 0.0,
        "missing_cases": missing_cases,
    }
    run = models.EvalRunRecord(
        eval_run_id=f"EVAL-{uuid4().hex[:12].upper()}",
        name=request.name,
        case_count=len(request.cases),
        metrics=metrics,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return {
        "eval_run_id": run.eval_run_id,
        "name": run.name,
        "case_count": run.case_count,
        "metrics": run.metrics,
        "created_at": run.created_at.isoformat(),
    }


def _get_case_or_404(db: Session, case_id: str) -> models.CaseRecord:
    record = db.scalar(select(models.CaseRecord).where(models.CaseRecord.case_id == case_id))
    if record is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return record


def _case_payload(db: Session, record: models.CaseRecord) -> dict:
    results = db.scalars(
        select(models.ExtractionResultRecord).where(models.ExtractionResultRecord.case_id == record.case_id)
    ).all()
    blocks = db.scalars(select(models.OcrBlockRecord).where(models.OcrBlockRecord.case_id == record.case_id)).all()
    audits = db.scalars(select(models.ReviewAuditRecord).where(models.ReviewAuditRecord.case_id == record.case_id)).all()
    latest_run = db.scalar(
        select(models.ProcessingRunRecord)
        .where(models.ProcessingRunRecord.case_id == record.case_id)
        .order_by(models.ProcessingRunRecord.created_at.desc())
        .limit(1)
    )
    return {
        "case_id": record.case_id,
        "filename": record.filename,
        "file_hash": record.file_hash,
        "status": record.status,
        "error_message": record.error_message,
        "created_at": record.created_at.isoformat(),
        "results": [_result_payload(result) for result in results],
        "ocr_blocks": [
            {
                "page": block.page,
                "text": block.redacted_text,
                "bbox": block.bbox,
                "confidence": block.confidence,
            }
            for block in blocks
        ],
        "audit_count": len(audits),
        "latest_run": _run_payload(latest_run) if latest_run else None,
        "quality": _quality_payload(latest_run),
    }


def _result_payload(result: models.ExtractionResultRecord) -> dict:
    return {
        "field_key": result.field_key,
        "raw_value": result.raw_value,
        "normalized_code": result.normalized_code,
        "confidence": result.confidence,
        "evidence_text": result.evidence_text,
        "page": result.page,
        "bbox": result.bbox or [],
        "reasoning_summary": result.reasoning_summary,
        "review_required": result.review_required,
        "error_code": result.error_code,
    }


def _run_payload(run: models.ProcessingRunRecord | None) -> dict | None:
    if run is None:
        return None
    return {
        "run_id": run.run_id,
        "status": run.status,
        "ocr_profile": run.ocr_profile,
        "layout_profile": run.layout_profile,
        "llm_profile": run.llm_profile,
        "parser_mode": run.parser_mode,
        "page_count": run.page_count,
        "ocr_block_count": run.ocr_block_count,
        "fragment_count": run.fragment_count,
        "avg_ocr_confidence": run.avg_ocr_confidence,
        "low_confidence_block_count": run.low_confidence_block_count,
        "quality_band": run.quality_band,
        "auto_accept_count": run.auto_accept_count,
        "review_required_count": run.review_required_count,
        "unknown_count": run.unknown_count,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "cached_input_tokens": getattr(run, "cached_input_tokens", 0),
        "cost_usd": run.cost_usd,
        "latency_ms": run.latency_ms,
        "step_timings": run.step_timings or {},
        "error_message": run.error_message,
        "created_at": run.created_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


def _quality_payload(run: models.ProcessingRunRecord | None) -> dict:
    if run is None:
        return {
            "page_count": 0,
            "ocr_block_count": 0,
            "fragment_count": 0,
            "avg_ocr_confidence": 0.0,
            "low_confidence_block_count": 0,
            "quality_band": "poor",
            "needs_vision_fallback": False,
        }
    return {
        "page_count": run.page_count,
        "ocr_block_count": run.ocr_block_count,
        "fragment_count": run.fragment_count,
        "avg_ocr_confidence": run.avg_ocr_confidence,
        "low_confidence_block_count": run.low_confidence_block_count,
        "quality_band": run.quality_band,
        "needs_vision_fallback": run.quality_band == "poor",
    }


def _fragment_payload(fragment: models.DocumentFragmentRecord) -> dict:
    return {
        "page": fragment.page,
        "reading_order": fragment.reading_order,
        "text": fragment.redacted_text,
        "bbox": fragment.bbox or [],
        "confidence": fragment.confidence,
        "section_name": fragment.section_name,
        "block_type": fragment.block_type,
        "source_kind": fragment.source_kind,
    }


def _model_call_payload(call: models.ModelCallLogRecord) -> dict:
    return {
        "call_id": call.call_id,
        "provider": call.provider,
        "model": call.model,
        "mode": call.mode,
        "field_keys": call.field_keys or [],
        "input_tokens": call.input_tokens,
        "output_tokens": call.output_tokens,
        "cached_input_tokens": getattr(call, "cached_input_tokens", 0),
        "cost_usd": call.cost_usd,
        "latency_ms": call.latency_ms,
        "status": call.status,
        "error_code": call.error_code,
        "created_at": call.created_at.isoformat(),
    }


def _vision_request_payload(record: models.VisionFallbackRequestRecord) -> dict:
    return {
        "request_id": record.request_id,
        "case_id": record.case_id,
        "page": record.page,
        "bbox": record.bbox or [],
        "status": record.status,
        "reason": record.reason,
        "reviewer": record.reviewer,
        "created_at": record.created_at.isoformat(),
        "approved_at": record.approved_at.isoformat() if record.approved_at else None,
    }
