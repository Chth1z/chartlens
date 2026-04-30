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
from app.domain.models import DocumentIR, ExtractionCandidate, ValidatedFieldResult
from app.services.deidentify import deidentify_document_ir
from app.services.evidence import blocks_for_group, build_evidence_packs, evidence_for_field
from app.services.ocr import build_document_ir, file_sha256
from app.services.provider import SemanticExtractionProvider, build_semantic_provider
from app.services.rules import rule_shortcut_extract
from app.services.secret_store import protect_text
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
    diagnostics: dict = {"steps": [], "llm_usage": [], "config_errors": validate_project_config()}
    try:
        payload = Path(case.file_path).read_bytes()
        case.status = "ocr"
        touch_case(case)
        db.commit()

        raw_document_ir = build_document_ir(Path(case.file_path), payload, document_id=case.case_id)
        case.raw_document_ir_json = _protect_document_ir(raw_document_ir)
        profile = load_document_profile(raw_document_ir.profile_id)
        document_ir = deidentify_document_ir(raw_document_ir, profile)
        diagnostics["steps"].append({"name": "ocr_document_ir", "blocks": len(document_ir.blocks)})

        case.document_ir_json = document_ir.model_dump_json()
        case.status = "extracting"
        touch_case(case)
        db.commit()

        provider = semantic_provider or build_semantic_provider()
        results = extract_document(document_ir, provider=provider)
        diagnostics["llm_usage"].append({"provider": provider.name, "route": provider.route, "usage": provider.last_usage})

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
        raise


def extract_document(document_ir: DocumentIR, *, provider: SemanticExtractionProvider) -> list[ValidatedFieldResult]:
    schema = load_extraction_schema()
    results_by_key: dict[str, ValidatedFieldResult] = {}
    online_allowed = document_ir.metadata.get("deidentification", {}).get("online_llm_allowed", True)
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
                    field.key: build_evidence_packs(document_ir, field, blocks=group_blocks)
                    for field in fields
                }
                skipped_candidates = {
                    field.key: _skipped_no_evidence(field)
                    for field in fields
                    if field.llm.skip_when_no_evidence and not evidence_by_field[field.key]
                }
                callable_fields = [field for field in fields if field.key not in skipped_candidates]
            try:
                candidates = (
                    provider.extract_group(document_ir=document_ir, group=group, fields=callable_fields, blocks=group_blocks)
                    if callable_fields
                    else []
                )
            except Exception as exc:
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
            candidates_by_key = {candidate.field_key: candidate for candidate in [*candidates, *skipped_candidates.values()]}
            candidates = [candidates_by_key.get(field.key) or _missing_provider_result(field) for field in fields]

        for field, candidate in zip(fields, candidates):
            field_evidence = evidence_for_field(document_ir, field, blocks=group_blocks)
            field_packs = build_evidence_packs(document_ir, field, blocks=group_blocks)
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
    return [results_by_key[field.key] for field in schema.fields if field.key in results_by_key]


def _rule_or_unknown(field, blocks):
    result = rule_shortcut_extract(field, blocks)
    if result is not None:
        return result
    return ExtractionCandidate(
        field_key=field.key,
        field_group_key=field.field_group_key,
        normalized_code="unknown",
        status="not_mentioned",
        evidence_type="no_evidence",
        reasoning_summary="规则未命中，保持 unknown。",
        review_required=True,
        error_code="RULE_MISS",
    )


def _missing_provider_result(field) -> ExtractionCandidate:
    return ExtractionCandidate(
        field_key=field.key,
        field_group_key=field.field_group_key,
        normalized_code="unknown",
        status="error",
        evidence_type="no_evidence",
        reasoning_summary="语义模型未返回该字段。",
        review_required=True,
        error_code="MISSING_PROVIDER_RESULT",
    )


def _skipped_no_evidence(field) -> ExtractionCandidate:
    return ExtractionCandidate(
        field_key=field.key,
        field_group_key=field.field_group_key,
        normalized_code="unknown",
        status="not_mentioned",
        evidence_type="no_evidence",
        reasoning_summary="未召回字段级证据，按配置跳过模型调用。",
        review_required=True,
        error_code="NO_EVIDENCE_CANDIDATES_SKIPPED_LLM",
        provenance={"source": "evidence_pack", "route": "skipped_no_evidence"},
        acceptance_reason="no_evidence_candidates",
        risk_level="medium",
        validation_state="needs_review",
    )


def _public_error_message(exc: Exception) -> str:
    text = str(exc)
    if text.startswith("OCR_ENGINE_UNAVAILABLE:"):
        return text[:2000]
    return f"{type(exc).__name__}: processing failed; see backend logs for details"


def _quality_summary(results: list[ValidatedFieldResult], document_ir: DocumentIR) -> dict:
    non_unknown = [result for result in results if result.normalized_code not in (None, "unknown")]
    evidence_covered = [result for result in non_unknown if result.evidence_span and result.evidence_block_id]
    return {
        "field_count": len(results),
        "auto_accept_count": len([result for result in results if result.auto_accepted]),
        "review_required_count": len([result for result in results if result.review_required]),
        "unknown_count": len([result for result in results if result.normalized_code in (None, "unknown")]),
        "evidence_coverage": len(evidence_covered) / len(non_unknown) if non_unknown else 1.0,
        "ocr_engine": document_ir.metadata.get("ocr_engine"),
        "ocr_cache_status": document_ir.metadata.get("ocr_cache_status"),
        "deidentification": document_ir.metadata.get("deidentification", {}),
    }


def _protect_document_ir(document_ir: DocumentIR) -> str | None:
    protected = protect_text(document_ir.model_dump_json())
    return json_dumps(protected) if protected else None


def _page_quality_for_result(document_ir: DocumentIR, candidate: ExtractionCandidate) -> dict | None:
    page = candidate.page
    if page is None and candidate.evidence_block_id:
        for block in document_ir.blocks:
            if block.block_id == candidate.evidence_block_id:
                page = block.page
                break
    for item in document_ir.metadata.get("ocr_page_quality", []):
        if isinstance(item, dict) and item.get("page") == page:
            return item
    return None


def _provider_usage_value(provider: SemanticExtractionProvider, candidate: ExtractionCandidate, key: str):
    if candidate.provenance.get("route") == "skipped_no_evidence":
        return None
    return getattr(provider, "last_usage", {}).get(key)
