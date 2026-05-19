from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import BoundedSemaphore

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config_loader import load_document_profile, load_extraction_schema, validate_project_config
from app.core.database import CaseRecord, FieldResultRecord, json_dumps, touch_case
from app.core.settings import settings
from app.domain.models import DocumentIR, ExtractionCandidate, ValidatedFieldResult
from app.services.deidentify import deidentify_document_ir
from app.services.document_context import build_document_context
from app.services.evidence_first import decisions_to_extraction_candidates
from app.services.evidence import (
    blocks_for_group,
    build_evidence_index,
    build_evidence_packs,
    evidence_for_field,
)
from app.services.layout_normalizer import normalize_document_layout
from app.services.ocr import build_document_ir, file_sha256
from app.services.observability import ProcessingTrace
from app.services.llm_provider.fallback import ConservativeLocalProvider, build_semantic_provider
from app.services.llm_provider.types import SemanticExtractionProvider
from app.services.pipeline_errors import _public_error_message, _protect_document_ir
from app.services.pipeline_evidence_first import (
    _extract_document_evidence_first,
    _missing_provider_result,
    _skipped_no_evidence,
    _rule_or_unknown,
)
from app.services.pipeline_quality import _quality_summary, _page_quality_for_result, _provider_usage_value
from app.services.rules import rule_shortcut_extract
from app.services.validation import unknown_result, validate_candidate


executor = ThreadPoolExecutor(max_workers=max(1, settings.case_workers))
queue_slots = BoundedSemaphore(max(1, settings.case_workers) + max(0, settings.max_pending_cases))
logger = logging.getLogger(__name__)


def create_case_record(db: Session, filename: str, payload: bytes) -> CaseRecord:
    case_id, safe_name, file_path = prepare_case_file(filename)
    file_path.write_bytes(payload)
    return create_case_record_from_saved_file(db, case_id, safe_name, file_path, file_sha256(payload))


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
        raise


def extract_document(
    document_ir: DocumentIR,
    *,
    provider: SemanticExtractionProvider,
    trace: ProcessingTrace | None = None,
) -> list[ValidatedFieldResult]:
    schema = load_extraction_schema()
    if schema.extraction_strategy == "evidence_first_multimodal":
        return _extract_document_evidence_first(document_ir, provider=provider, schema=schema, trace=trace)
    results_by_key: dict[str, ValidatedFieldResult] = {}
    online_allowed = document_ir.metadata.get("deidentification", {}).get("online_llm_allowed", True)
    # M1-002: build the case-wide FTS5 evidence index once. Group-scoped
    # `blocks` arguments to `build_evidence_packs` below still work because
    # the indexed path filters scores by block_id at query time, and the
    # caller passes its scoped block list as the `blocks` argument so
    # ranking, dedupe, and context-window math operate on that subset.
    case_index = build_evidence_index(document_ir.blocks)
    try:
        for group in schema.field_groups:
            fields = schema.fields_for_group(group.key)
            if not fields:
                continue
            group_blocks = blocks_for_group(document_ir, group)
            if group.semantic_strategy == "rule_shortcut":
                candidates = [_rule_or_unknown(field, group_blocks) for field in fields]
            elif not online_allowed:
                candidates = [
                    ExtractionCandidate(
                        field_key=field.key,
                        field_group_key=field.field_group_key,
                        normalized_code="unknown",
                        status="error",
                        evidence_type="no_evidence",
                        reasoning_summary="脱敏风险未通过在线模型外发门禁，字段进入人工复核。",
                        review_required=True,
                        error_code="DEIDENTIFICATION_RISK_BLOCKED_ONLINE_LLM",
                        validation_state="needs_review",
                        risk_level="high",
                        provenance={"source": "deidentification_gate"},
                    )
                    for field in fields
                ]
            else:
                skipped_candidates: dict[str, ExtractionCandidate] = {}
                callable_fields = fields
                if online_allowed:
                    evidence_by_field = {
                        field.key: build_evidence_packs(document_ir, field, blocks=group_blocks, index=case_index)
                        for field in fields
                    }
                    skipped_candidates = {
                        field.key: _skipped_no_evidence(field)
                        for field in fields
                        if field.llm.skip_when_no_evidence and not evidence_by_field[field.key]
                    }
                    callable_fields = [field for field in fields if field.key not in skipped_candidates]
                try:
                    model_started = time.perf_counter()
                    candidates = (
                        provider.extract_group(document_ir=document_ir, group=group, fields=callable_fields, blocks=group_blocks)
                        if callable_fields
                        else []
                    )
                except Exception as exc:
                    if trace is not None and callable_fields:
                        trace.record_model_call(
                            stage=f"group:{group.key}",
                            provider=provider,
                            fields=callable_fields,
                            usage=getattr(provider, "last_usage", {}),
                            started_perf=model_started,
                            status="failed",
                            error_code="LLM_PROVIDER_FAILED",
                            error_message=str(exc),
                        )
                    candidates = [
                        ExtractionCandidate(
                            field_key=field.key,
                            field_group_key=field.field_group_key,
                            normalized_code="unknown",
                            status="error",
                            evidence_type="no_evidence",
                            reasoning_summary="语义模型调用失败，降级人工复核。",
                            review_required=True,
                            error_code=f"LLM_PROVIDER_FAILED: {exc}",
                        )
                        for field in callable_fields
                    ]
                else:
                    if trace is not None and callable_fields:
                        trace.record_model_call(
                            stage=f"group:{group.key}",
                            provider=provider,
                            fields=callable_fields,
                            usage=getattr(provider, "last_usage", {}),
                            started_perf=model_started,
                        )
                candidates_by_key = {candidate.field_key: candidate for candidate in [*candidates, *skipped_candidates.values()]}
                candidates = [candidates_by_key.get(field.key) or _missing_provider_result(field) for field in fields]

            for field, candidate in zip(fields, candidates):
                field_evidence = evidence_for_field(document_ir, field, blocks=group_blocks, index=case_index)
                field_packs = build_evidence_packs(document_ir, field, blocks=group_blocks, index=case_index)
                candidate = candidate.model_copy(
                    update={
                        "evidence_candidates": field_evidence,
                        "evidence_packs": field_packs,
                        "model_profile_id": getattr(getattr(provider, "profile", None), "profile_id", None),
                        "ocr_engine": document_ir.metadata.get("ocr_engine"),
                        "provenance": {
                            **candidate.provenance,
                            "provider": provider.name,
                            "route": candidate.provenance.get("route", provider.route),
                            "group": group.key,
                            "llm_cache_status": _provider_usage_value(provider, candidate, "llm_cache_status"),
                            "llm_cache_key": _provider_usage_value(provider, candidate, "llm_cache_key"),
                            "ocr_page_quality": _page_quality_for_result(document_ir, candidate),
                        },
                    }
                )
                results_by_key[field.key] = validate_candidate(candidate, field, document_ir)
    finally:
        case_index.close()
    return [results_by_key[field.key] for field in schema.fields if field.key in results_by_key]
