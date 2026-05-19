"""Cases CRUD plus processing routes."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.contracts import (
    DocumentIrResponse,
    MaintenanceResponse,
    SourceOcrResponse,
    VisionFallbackRecordResponse,
)
from app.core.database import (
    CaseRecord,
    FieldResultRecord,
    VisionFallbackRequestRecord,
    get_db,
)
from app.core.settings import settings
from app.domain.models import CaseSummary, ReviewDecision, ValidatedFieldResult
from app.services.export import build_export_workbook
from app.services.pipeline import enqueue_case, process_case
from app.services.progress import progress_bus
from app.services.review import apply_review
from app.services.source_ocr import build_source_ocr_payload
from app.services.source_pages import SourcePageError, resolve_case_source_page

from ._helpers import (
    _case_document_payload,
    _case_raw_document_payload,
    _case_summary,
    _remove_upload_parent,
    _require_case,
    _results_for_case,
    _save_upload_as_case,
    _vision_fallback_record_payload,
)


router = APIRouter()


class VisionFallbackRequestPayload(BaseModel):
    field_key: str | None = None
    page: int = Field(default=1, ge=1)
    bbox: list[float] = Field(default_factory=list)
    reason: str = ""
    reviewer: str = "local-reviewer"
    manual_redaction_confirmed: bool = False


@router.post("/cases", response_model=CaseSummary)
async def upload_case(file: Annotated[UploadFile, File()], db: Annotated[Session, Depends(get_db)]) -> CaseSummary:
    case = await _save_upload_as_case(file, db)
    if settings.auto_process_uploads:
        if not enqueue_case(case.case_id):
            file_parent = Path(case.file_path).parent
            db.delete(case)
            db.commit()
            _remove_upload_parent(file_parent)
            raise HTTPException(status_code=429, detail="Case processing queue is full; retry later")
    return _case_summary(case)


@router.get("/cases", response_model=list[CaseSummary])
def list_cases(db: Annotated[Session, Depends(get_db)]) -> list[CaseSummary]:
    cases = db.execute(select(CaseRecord).where(CaseRecord.status != "archived").order_by(CaseRecord.created_at.desc())).scalars().all()
    return [_case_summary(case) for case in cases]


@router.get("/cases/{case_id}", response_model=CaseSummary)
def get_case(case_id: str, db: Annotated[Session, Depends(get_db)]) -> CaseSummary:
    case = _require_case(db, case_id)
    return _case_summary(case)


@router.get("/cases/{case_id}/progress")
async def case_progress_stream(case_id: str, db: Annotated[Session, Depends(get_db)]) -> StreamingResponse:
    """Stream SSE events for case processing progress.

    Emits `event: progress` at each stage transition and `event: complete`
    when the case reaches a terminal state (completed/failed). Sends a
    heartbeat comment every 15 seconds to keep the connection alive.
    """
    _require_case(db, case_id)

    async def event_generator():
        queue = await progress_bus.subscribe(case_id)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # Heartbeat to keep connection alive
                    yield ": heartbeat\n\n"
                    continue

                if event is None:
                    # Stream closed by publisher
                    break

                if event.stage in ("completed", "failed"):
                    data = json.dumps(
                        {"case_id": event.case_id, "stage": event.stage, "progress": event.progress},
                        ensure_ascii=False,
                    )
                    yield f"event: complete\ndata: {data}\n\n"
                    break
                else:
                    data = json.dumps(event.to_dict(), ensure_ascii=False)
                    yield f"event: progress\ndata: {data}\n\n"
        finally:
            progress_bus.unsubscribe(case_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/cases/{case_id}/reprocess", response_model=CaseSummary)
def reprocess_case(case_id: str, db: Annotated[Session, Depends(get_db)]) -> CaseSummary:
    case = _require_case(db, case_id)
    process_case(db, case)
    return _case_summary(case)


@router.get("/cases/{case_id}/document-ir", response_model=DocumentIrResponse)
def get_document_ir(case_id: str, db: Annotated[Session, Depends(get_db)]) -> dict:
    case = _require_case(db, case_id)
    return json.loads(case.document_ir_json) if case.document_ir_json else {"blocks": [], "sections": []}


@router.get("/cases/{case_id}/source-ocr", response_model=SourceOcrResponse)
def get_source_ocr(case_id: str, db: Annotated[Session, Depends(get_db)]) -> dict:
    case = _require_case(db, case_id)
    return build_source_ocr_payload(_case_raw_document_payload(case), _case_document_payload(case))


@router.get("/cases/{case_id}/source-pages/{page}")
def get_case_source_page(case_id: str, page: int, db: Annotated[Session, Depends(get_db)]) -> Response:
    case = _require_case(db, case_id)
    try:
        source_page = resolve_case_source_page(case, page)
    except SourcePageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    headers = {
        "Cache-Control": "private, max-age=3600",
        "X-EYEX-Source-Page-Cache": source_page.cache_status,
    }
    if source_page.dpi is not None:
        headers["X-EYEX-Source-Page-DPI"] = str(source_page.dpi)
    if source_page.width is not None:
        headers["X-EYEX-Source-Page-Width"] = str(source_page.width)
    if source_page.height is not None:
        headers["X-EYEX-Source-Page-Height"] = str(source_page.height)
    return FileResponse(source_page.path, media_type=source_page.media_type, headers=headers)


@router.get("/cases/{case_id}/results", response_model=list[ValidatedFieldResult])
def get_results(case_id: str, db: Annotated[Session, Depends(get_db)]) -> list[ValidatedFieldResult]:
    _require_case(db, case_id)
    return _results_for_case(db, case_id)


@router.post("/cases/{case_id}/review", response_model=ValidatedFieldResult)
def review_field(case_id: str, decision: ReviewDecision, db: Annotated[Session, Depends(get_db)]) -> ValidatedFieldResult:
    _require_case(db, case_id)
    record = db.execute(
        select(FieldResultRecord).where(
            FieldResultRecord.case_id == case_id,
            FieldResultRecord.field_key == decision.field_key,
        )
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Field result not found")
    try:
        return apply_review(record, decision, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/cases/{case_id}/export")
def export_case(case_id: str, db: Annotated[Session, Depends(get_db)]) -> Response:
    _require_case(db, case_id)
    data = build_export_workbook(_results_for_case(db, case_id))
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{case_id}.xlsx"'},
    )


@router.delete("/cases/{case_id}", response_model=MaintenanceResponse)
def delete_case(case_id: str, db: Annotated[Session, Depends(get_db)]) -> dict:
    case = _require_case(db, case_id)
    case.status = "archived"
    case.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "affected_count": 1, "message": "病例已从列表移除，原始文件和审计日志已保留。"}


@router.post("/cases/{case_id}/vision-fallback-requests", response_model=VisionFallbackRecordResponse)
def vision_fallback_request(case_id: str, payload: VisionFallbackRequestPayload, db: Annotated[Session, Depends(get_db)]) -> dict:
    _require_case(db, case_id)
    now = datetime.now(timezone.utc)
    record = VisionFallbackRequestRecord(
        request_id=f"vision-{case_id}-{uuid.uuid4().hex[:12]}",
        case_id=case_id,
        field_key=payload.field_key,
        page=payload.page,
        bbox_json=json.dumps(payload.bbox, ensure_ascii=False),
        status="recorded",
        reason=payload.reason,
        reviewer=payload.reviewer,
        manual_redaction_confirmed=1 if payload.manual_redaction_confirmed else 0,
        created_at=now,
        approved_at=now if payload.manual_redaction_confirmed else None,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return _vision_fallback_record_payload(record)
