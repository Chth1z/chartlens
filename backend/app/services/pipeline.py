from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import BoundedSemaphore

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config_loader import load_document_profile, load_extraction_schema, validate_project_config
from app.core.database import CaseRecord, FieldResultRecord, json_dumps, touch_case
from app.core.settings import settings
from app.domain.models import DocumentIR, ValidatedFieldResult
from app.services.deidentify import deidentify_document_ir
from app.services.layout_normalizer import normalize_document_layout
from app.services.ocr import build_document_ir, file_sha256
from app.services.observability import ProcessingTrace
from app.services.progress import ProgressEvent, progress_bus
from app.services.llm_provider.fallback import build_semantic_provider
from app.services.llm_provider.types import SemanticExtractionProvider
from app.services.pipeline_errors import _public_error_message, _protect_document_ir
from app.services.pipeline_evidence_first import (
    _async_extract_document_evidence_first,
    _extract_document_evidence_first,
)
from app.services.pipeline_quality import _quality_summary


executor = ThreadPoolExecutor(max_workers=max(1, settings.case_workers))
queue_slots = BoundedSemaphore(max(1, settings.case_workers) + max(0, settings.max_pending_cases))
logger = logging.getLogger(__name__)


def prepare_case_file(filename: str) -> tuple[str, str, Path]:
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    case_id = f"CASE-{uuid.uuid4().hex[:12].upper()}"
    safe_name = Path(filename).name or "case.txt"
    file_path = settings.storage_dir / "uploads" / case_id / safe_name
    file_path.parent.mkdir(parents=True, exist_ok=True)
    return case_id, safe_name, file_path


def create_case_record_from_saved_file(
    db: Session,
    case_id: str,
    safe_name: str,
    file_path: Path,
    file_hash: str,
) -> CaseRecord:
    record = CaseRecord(
        case_id=case_id,
        filename=safe_name,
        file_hash=file_hash,
        file_path=str(file_path),
        status="queued",
        diagnostics_json=json_dumps({"steps": [], "config_errors": validate_project_config()}),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def enqueue_case(case_id: str) -> bool:
    if not queue_slots.acquire(blocking=False):
        return False
    try:
        future = executor.submit(_process_case_in_new_session, case_id)
    except Exception:
        queue_slots.release()
        raise
    future.add_done_callback(lambda _: queue_slots.release())
    return True


def _process_case_in_new_session(case_id: str) -> None:
    from app.core.database import SessionLocal, get_case_or_none

    db = SessionLocal()
    try:
        case = get_case_or_none(db, case_id)
        if case is None:
            return
        process_case(db, case)
    finally:
        db.close()


def process_case(
    db: Session,
    case: CaseRecord,
    *,
    semantic_provider: SemanticExtractionProvider | None = None,
) -> list[ValidatedFieldResult]:
    trace = ProcessingTrace.start(db, case)
    diagnostics: dict = {
        "run_id": trace.run.run_id,
        "steps": [],
        "llm_usage": [],
        "config_errors": validate_project_config(),
    }
    try:
        case.status = "ocr"
        touch_case(case)
        db.commit()
        progress_bus.publish(case.case_id, ProgressEvent(
            case_id=case.case_id,
            stage="ocr",
            step="ocr_document_ir",
            progress=0.1,
            started_at=trace.run.started_at.isoformat() if trace.run.started_at else "",
            message="OCR processing...",
        ))

        with trace.step(
            "load_upload",
            {"filename": case.filename, "file_hash": case.file_hash, "suffix": Path(case.file_path).suffix.lower()},
        ):
            payload = Path(case.file_path).read_bytes()

        with trace.step("ocr_document_ir", {"filename": case.filename, "bytes": len(payload)}):
            raw_document_ir = build_document_ir(Path(case.file_path), payload, document_id=case.case_id)
            case.raw_document_ir_json = _protect_document_ir(raw_document_ir)

        profile = load_document_profile(raw_document_ir.profile_id)
        with trace.step("normalize_document_layout", {"blocks": len(raw_document_ir.blocks)}):
            normalized_document_ir = normalize_document_layout(raw_document_ir, profile)

        with trace.step("deidentify_document_ir", {"blocks": len(normalized_document_ir.blocks)}):
            document_ir = deidentify_document_ir(normalized_document_ir, profile)
        diagnostics["steps"].append({"name": "ocr_document_ir", "blocks": len(raw_document_ir.blocks)})
        diagnostics["steps"].append(
            {"name": "layout_normalization", **normalized_document_ir.metadata.get("layout_normalization", {})}
        )

        case.document_ir_json = document_ir.model_dump_json()
        case.status = "extracting"
        touch_case(case)
        db.commit()
        progress_bus.publish(case.case_id, ProgressEvent(
            case_id=case.case_id,
            stage="extracting",
            step="extract_document",
            progress=0.5,
            started_at=trace.run.started_at.isoformat() if trace.run.started_at else "",
            message="Extracting fields...",
        ))

        provider = semantic_provider or build_semantic_provider()
        with trace.step("extract_document", {"provider": provider.name, "route": provider.route}):
            results = extract_document(document_ir, provider=provider, trace=trace)
        diagnostics["llm_usage"].append({"provider": provider.name, "route": provider.route, "usage": provider.last_usage})

        with trace.step("persist_results", {"result_count": len(results)}):
            db.execute(delete(FieldResultRecord).where(FieldResultRecord.case_id == case.case_id))
            for result in results:
                db.add(
                    FieldResultRecord(
                        case_id=case.case_id,
                        field_key=result.field_key,
                        payload_json=result.model_dump_json(),
                        reviewed=0,
                    )
                )
            case.status = "completed"
            diagnostics["steps"].append({"name": "validated_results", "results": len(results)})
            diagnostics["quality"] = _quality_summary(results, document_ir)
            case.diagnostics_json = json_dumps(diagnostics)
            touch_case(case)
            db.commit()
        trace.finish_completed(results=results, document_ir=document_ir, diagnostics=diagnostics)
        progress_bus.publish(case.case_id, ProgressEvent(
            case_id=case.case_id,
            stage="completed",
            progress=1.0,
            message="Processing complete.",
        ))
        db.refresh(case)
        return results
    except Exception as exc:
        logger.exception("Case processing failed for %s", case.case_id)
        diagnostics["error_code"] = "PROCESSING_FAILED"
        diagnostics["error_type"] = type(exc).__name__
        diagnostics["error"] = _public_error_message(exc)
        case.status = "failed"
        case.diagnostics_json = json_dumps(diagnostics)
        touch_case(case)
        db.commit()
        trace.finish_failed(diagnostics=diagnostics)
        progress_bus.publish(case.case_id, ProgressEvent(
            case_id=case.case_id,
            stage="failed",
            progress=1.0,
            message="Processing failed.",
        ))
        raise


def extract_document(
    document_ir: DocumentIR,
    *,
    provider: SemanticExtractionProvider,
    trace: ProcessingTrace | None = None,
) -> list[ValidatedFieldResult]:
    schema = load_extraction_schema()
    if schema.extraction_strategy != "evidence_first_multimodal":
        raise ValueError(
            f"Unsupported extraction_strategy {schema.extraction_strategy!r}. "
            "Only 'evidence_first_multimodal' is supported. The legacy extract_group "
            "path was removed — update your extraction schema."
        )
    return _extract_document_evidence_first(document_ir, provider=provider, schema=schema, trace=trace)


# ---------------------------------------------------------------------------
# Async pipeline path (S2-002)
# ---------------------------------------------------------------------------


async def async_extract_document(
    document_ir: DocumentIR,
    *,
    provider: SemanticExtractionProvider,
    trace: ProcessingTrace | None = None,
) -> list[ValidatedFieldResult]:
    """Async version of extract_document. Uses async LLM calls."""
    schema = load_extraction_schema()
    if schema.extraction_strategy != "evidence_first_multimodal":
        raise ValueError(
            f"Unsupported extraction_strategy {schema.extraction_strategy!r}. "
            "Only 'evidence_first_multimodal' is supported."
        )
    return await _async_extract_document_evidence_first(
        document_ir, provider=provider, schema=schema, trace=trace
    )


async def enqueue_case_async(case_id: str) -> bool:
    """Async version of enqueue_case.

    Uses asyncio.to_thread for DB operations (SQLAlchemy is sync) and
    the async pipeline path for LLM calls. This allows multiple cases
    to have their LLM calls in-flight concurrently without blocking
    the event loop.
    """
    import asyncio
    from app.core.database import SessionLocal, get_case_or_none

    db = await asyncio.to_thread(SessionLocal)
    try:
        case = await asyncio.to_thread(get_case_or_none, db, case_id)
        if case is None:
            return False
        await _async_process_case(db, case)
        return True
    finally:
        await asyncio.to_thread(db.close)


async def _async_process_case(db, case: CaseRecord) -> list[ValidatedFieldResult]:
    """Async case processing: DB ops in to_thread, LLM calls async.

    This is a simplified async path that handles the extraction phase
    asynchronously. OCR and DB persistence remain synchronous (wrapped
    in to_thread) since they are CPU-bound or require sync SQLAlchemy.
    """
    import asyncio

    # OCR phase (CPU-bound, stays sync)
    case.status = "ocr"
    touch_case(case)
    await asyncio.to_thread(db.commit)

    payload = await asyncio.to_thread(Path(case.file_path).read_bytes)
    raw_document_ir = await asyncio.to_thread(
        build_document_ir, Path(case.file_path), payload, case.case_id
    )
    case.raw_document_ir_json = _protect_document_ir(raw_document_ir)

    profile = load_document_profile(raw_document_ir.profile_id)
    normalized_document_ir = await asyncio.to_thread(
        normalize_document_layout, raw_document_ir, profile
    )
    document_ir = await asyncio.to_thread(
        deidentify_document_ir, normalized_document_ir, profile
    )

    case.document_ir_json = document_ir.model_dump_json()
    case.status = "extracting"
    touch_case(case)
    await asyncio.to_thread(db.commit)

    # Extraction phase (async LLM calls)
    provider = build_semantic_provider()
    results = await async_extract_document(document_ir, provider=provider)

    # Persist results (sync DB)
    await asyncio.to_thread(_persist_results_sync, db, case, results, document_ir)
    return results


def _persist_results_sync(
    db, case: CaseRecord, results: list[ValidatedFieldResult], document_ir: DocumentIR
) -> None:
    """Sync helper for persisting extraction results to DB."""
    db.execute(delete(FieldResultRecord).where(FieldResultRecord.case_id == case.case_id))
    for result in results:
        db.add(
            FieldResultRecord(
                case_id=case.case_id,
                field_key=result.field_key,
                payload_json=result.model_dump_json(),
                reviewed=0,
            )
        )
    case.status = "completed"
    case.diagnostics_json = json_dumps({"steps": [], "quality": _quality_summary(results, document_ir)})
    touch_case(case)
    db.commit()
