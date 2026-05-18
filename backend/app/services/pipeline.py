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
from app.services.evidence import blocks_for_group, build_evidence_packs, evidence_for_field
from app.services.layout_normalizer import normalize_document_layout
from app.services.ocr import build_document_ir, file_sha256
from app.services.observability import ProcessingTrace
from app.services.llm_provider.fallback import ConservativeLocalProvider, build_semantic_provider
from app.services.llm_provider.types import SemanticExtractionProvider
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


def _extract_document_evidence_first(
    document_ir: DocumentIR,
    *,
    provider: SemanticExtractionProvider,
    schema,
    trace: ProcessingTrace | None = None,
) -> list[ValidatedFieldResult]:
    phase_one_fields = [field for field in schema.fields if field.phase == 1]

    # E1-005 rule_pre_accepted shortcut: when a phase-1 field belongs to a
    # group whose `semantic_strategy == "rule_shortcut"` AND the rule path
    # returns a candidate at confidence >= 0.95, bypass the LLM evidence-
    # first pipeline entirely. This closes the eval-mock-003 / age LLM gap
    # surfaced by E1-010 Phase A and reduces token cost on demographics
    # group calls. See docs/ROADMAP.md E1-005 and docs/DECISIONS.md
    # 2026-05-18 "rule_pre_accepted shortcut bypasses LLM".
    rule_shortcut_candidates: dict[str, ExtractionCandidate] = {}
    llm_fields: list = []
    for field in phase_one_fields:
        group = schema.group_by_key(field.field_group_key)
        if group.semantic_strategy != "rule_shortcut":
            llm_fields.append(field)
            continue
        rule_candidate = rule_shortcut_extract(field, document_ir.blocks)
        if rule_candidate is None or rule_candidate.confidence < 0.95:
            llm_fields.append(field)
            continue
        rule_shortcut_candidates[field.key] = rule_candidate.model_copy(
            update={
                "acceptance_reason": "rule_pre_accepted",
                "provenance": {
                    **rule_candidate.provenance,
                    "source": "rule_shortcut",
                    "skipped_llm": True,
                    # Mirror the LLM evidence-first path's `decision_status:
                    # PASS` so the export gate
                    # (validation_state == "accepted" AND
                    #  provenance.decision_status == "PASS") still admits
                    # rule-pre-accepted candidates. Without this key the
                    # template's `pass_decision_status: PASS` gate would
                    # reject them and gender / age would land in the
                    # workbook as `unknown`, regressing
                    # test_table_cell_demographics_flow_from_layout_to_export.
                    "decision_status": "PASS",
                },
            }
        )

    if trace is not None:
        with trace.step(
            "build_document_context",
            {"field_count": len(llm_fields), "block_count": len(document_ir.blocks)},
        ):
            context = build_document_context(document_ir)
    else:
        context = build_document_context(document_ir)
    online_allowed = document_ir.metadata.get("deidentification", {}).get("online_llm_allowed", True)
    evidence_provider = provider if online_allowed else ConservativeLocalProvider()
    results_by_key: dict[str, ValidatedFieldResult] = {}

    try:
        if trace is not None:
            with trace.step("collect_evidence", {"field_count": len(llm_fields)}):
                model_started = time.perf_counter()
                try:
                    evidence_by_field = evidence_provider.collect_evidence(document_context=context, fields=llm_fields)
                except Exception as exc:
                    trace.record_model_call(
                        stage="collect_evidence",
                        provider=evidence_provider,
                        fields=llm_fields,
                        usage=getattr(evidence_provider, "last_usage", {}),
                        started_perf=model_started,
                        status="failed",
                        error_code="EVIDENCE_COLLECTION_FAILED",
                        error_message=str(exc),
                    )
                    raise
                trace.record_model_call(
                    stage="collect_evidence",
                    provider=evidence_provider,
                    fields=llm_fields,
                    usage=getattr(evidence_provider, "last_usage", {}),
                    started_perf=model_started,
                )
            with trace.step("adjudicate_fields", {"field_count": len(llm_fields)}):
                decisions_by_field = evidence_provider.adjudicate_fields(
                    document_context=context,
                    fields=llm_fields,
                    evidence_by_field=evidence_by_field,
                )
            with trace.step("verify_against_document", {"field_count": len(llm_fields)}):
                decisions_by_field = evidence_provider.verify_against_document(
                    document_context=context,
                    fields=llm_fields,
                    decisions_by_field=decisions_by_field,
                )
            with trace.step("candidate_conversion", {"field_count": len(llm_fields)}):
                candidates = decisions_to_extraction_candidates(llm_fields, decisions_by_field)
        else:
            evidence_by_field = evidence_provider.collect_evidence(document_context=context, fields=llm_fields)
            decisions_by_field = evidence_provider.adjudicate_fields(
                document_context=context,
                fields=llm_fields,
                evidence_by_field=evidence_by_field,
            )
            decisions_by_field = evidence_provider.verify_against_document(
                document_context=context,
                fields=llm_fields,
                decisions_by_field=decisions_by_field,
            )
            candidates = decisions_to_extraction_candidates(llm_fields, decisions_by_field)
    except Exception as exc:
        logger.exception("Evidence-first extraction failed for %s", document_ir.document_id)
        candidates = [
            ExtractionCandidate(
                field_key=field.key,
                field_group_key=field.field_group_key,
                normalized_code="unknown",
                status="error",
                evidence_type="no_evidence",
                reasoning_summary="证据优先抽取链路失败，字段降级进入人工复核。",
                review_required=True,
                error_code=f"EVIDENCE_FIRST_FAILED: {exc}",
                risk_level="high",
                provenance={"source": "evidence_first", "route": "failed"},
            )
            for field in llm_fields
        ]

    candidates_by_key = {candidate.field_key: candidate for candidate in candidates}
    # Rule-pre-accepted candidates win because they did not pass through the
    # LLM. This merge happens after `candidates_by_key` is constructed from
    # the LLM stages so the bypassed fields cannot be overwritten by a stale
    # LLM result if one ever leaks in (e.g., from a misbehaving fake).
    candidates_by_key.update(rule_shortcut_candidates)
    all_blocks = document_ir.blocks
    for field in phase_one_fields:
        group = schema.group_by_key(field.field_group_key)
        candidate = candidates_by_key.get(field.key) or _missing_provider_result(field)
        candidate = candidate.model_copy(
            update={
                "evidence_candidates": candidate.evidence_candidates or evidence_for_field(document_ir, field, blocks=all_blocks),
                "evidence_packs": build_evidence_packs(document_ir, field, blocks=all_blocks),
                "model_profile_id": getattr(getattr(evidence_provider, "profile", None), "profile_id", None),
                "ocr_engine": document_ir.metadata.get("ocr_engine"),
                "provenance": {
                    **candidate.provenance,
                    "provider": evidence_provider.name,
                    "route": candidate.provenance.get("route", evidence_provider.route),
                    "group": group.key,
                    "extraction_strategy": "evidence_first_multimodal",
                    "document_context_version": context.metadata.get("context_version"),
                    "llm_cache_status": _provider_usage_value(evidence_provider, candidate, "llm_cache_status"),
                    "llm_cache_key": _provider_usage_value(evidence_provider, candidate, "llm_cache_key"),
                    "ocr_page_quality": _page_quality_for_result(document_ir, candidate),
                },
            }
        )
        validated = validate_candidate(candidate, field, document_ir)
        # Validation may overwrite the acceptance_reason to
        # "high_confidence_evidence_validated" when auto-acceptance fires.
        # For rule-pre-accepted fields we want the more specific reason to
        # survive so diagnostics surface that the LLM was skipped. The
        # auto_accepted flag remains as validate_candidate decided.
        if field.key in rule_shortcut_candidates:
            validated = validated.model_copy(update={"acceptance_reason": "rule_pre_accepted"})
        results_by_key[field.key] = validated
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
    avg_confidence = (
        sum(float(block.confidence or 0) for block in document_ir.blocks) / len(document_ir.blocks)
        if document_ir.blocks
        else 0
    )
    metadata = document_ir.metadata or {}
    return {
        "field_count": len(results),
        "page_count": len({block.page for block in document_ir.blocks}) if document_ir.blocks else 0,
        "ocr_block_count": len(document_ir.blocks),
        "avg_ocr_confidence": avg_confidence,
        "low_confidence_block_count": len([block for block in document_ir.blocks if float(block.confidence or 0) < 0.75]),
        "quality_band": "good" if avg_confidence >= 0.9 else "fair" if avg_confidence >= 0.75 else "poor",
        "auto_accept_count": len([result for result in results if result.auto_accepted]),
        "review_required_count": len([result for result in results if result.review_required]),
        "unknown_count": len([result for result in results if result.normalized_code in (None, "unknown")]),
        "evidence_coverage": len(evidence_covered) / len(non_unknown) if non_unknown else 1.0,
        "input_kind": metadata.get("input_kind"),
        "ocr_adapter": metadata.get("ocr_adapter", "intelligent_document"),
        "ocr_engine": metadata.get("ocr_engine"),
        "ocr_intelligent_status": metadata.get("ocr_intelligent_status"),
        "ocr_attempted_engines": metadata.get("ocr_attempted_engines", []),
        "ocr_unavailable_engines": metadata.get("ocr_unavailable_engines", []),
        "ocr_unavailable_reasons": metadata.get("ocr_unavailable_reasons", {}),
        "ocr_engine_errors": metadata.get("ocr_engine_errors", {}),
        "ocr_trace": metadata.get("ocr_trace", {}),
        "ocr_page_quality": metadata.get("ocr_page_quality", []),
        "ocr_cache_status": metadata.get("ocr_cache_status"),
        "deidentification": metadata.get("deidentification", {}),
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
