from __future__ import annotations

import logging
import time

from app.domain.models import DocumentIR, ExtractionCandidate, ValidatedFieldResult
from app.services.document_context import build_document_context
from app.services.evidence_first import decisions_to_extraction_candidates
from app.services.evidence import (
    build_evidence_index,
    build_evidence_packs,
    evidence_for_field,
)
from app.services.llm_provider.fallback import ConservativeLocalProvider
from app.services.llm_provider.types import SemanticExtractionProvider
from app.services.observability import ProcessingTrace
from app.services.pipeline_quality import _page_quality_for_result, _provider_usage_value
from app.services.rules import rule_shortcut_extract
from app.services.validation import validate_candidate


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers (extracted to eliminate sync/async duplication)
# ---------------------------------------------------------------------------


def _partition_rule_shortcut_fields(schema, phase_one_fields, blocks):
    """Partition phase-1 fields into rule-shortcut candidates and LLM fields.

    Returns (rule_shortcut_candidates, llm_fields) where rule_shortcut_candidates
    is a dict mapping field key -> ExtractionCandidate for fields resolved by rule
    shortcut, and llm_fields is the list of fields that still need LLM processing.
    """
    rule_shortcut_candidates: dict[str, ExtractionCandidate] = {}
    llm_fields: list = []
    for field in phase_one_fields:
        group = schema.group_by_key(field.field_group_key)
        if group.semantic_strategy != "rule_shortcut":
            llm_fields.append(field)
            continue
        rule_candidate = rule_shortcut_extract(field, blocks)
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
                    "decision_status": "PASS",
                },
            }
        )
    return rule_shortcut_candidates, llm_fields


def _error_fallback_candidates(llm_fields, error: Exception, *, async_mode: bool = False):
    """Generate fallback ExtractionCandidate list when the evidence pipeline fails."""
    if async_mode:
        summary = "异步证据优先抽取链路失败，字段降级进入人工复核。"
        code_prefix = "ASYNC_EVIDENCE_FIRST_FAILED"
        route = "async_failed"
    else:
        summary = "证据优先抽取链路失败，字段降级进入人工复核。"
        code_prefix = "EVIDENCE_FIRST_FAILED"
        route = "failed"
    return [
        ExtractionCandidate(
            field_key=field.key,
            field_group_key=field.field_group_key,
            normalized_code="unknown",
            status="error",
            evidence_type="no_evidence",
            reasoning_summary=summary,
            review_required=True,
            error_code=f"{code_prefix}: {error}",
            risk_level="high",
            provenance={"source": "evidence_first", "route": route},
        )
        for field in llm_fields
    ]


def _build_validated_results(
    phase_one_fields,
    candidates_by_key: dict[str, ExtractionCandidate],
    rule_shortcut_candidates: dict[str, ExtractionCandidate],
    evidence_provider,
    document_ir: DocumentIR,
    context,
    schema,
    all_blocks,
    *,
    extraction_strategy: str,
) -> list[ValidatedFieldResult]:
    """Merge candidates, attach evidence packs, validate, and return ordered results."""
    candidates_by_key.update(rule_shortcut_candidates)
    case_index = build_evidence_index(all_blocks)
    results_by_key: dict[str, ValidatedFieldResult] = {}
    try:
        for field in phase_one_fields:
            group = schema.group_by_key(field.field_group_key)
            candidate = candidates_by_key.get(field.key) or _missing_provider_result(field)
            candidate = candidate.model_copy(
                update={
                    "evidence_candidates": candidate.evidence_candidates or evidence_for_field(document_ir, field, blocks=all_blocks, index=case_index),
                    "evidence_packs": build_evidence_packs(document_ir, field, blocks=all_blocks, index=case_index),
                    "model_profile_id": getattr(getattr(evidence_provider, "profile", None), "profile_id", None),
                    "ocr_engine": document_ir.metadata.get("ocr_engine"),
                    "provenance": {
                        **candidate.provenance,
                        "provider": evidence_provider.name,
                        "route": candidate.provenance.get("route", evidence_provider.route),
                        "group": group.key,
                        "extraction_strategy": extraction_strategy,
                        "document_context_version": context.metadata.get("context_version"),
                        "llm_cache_status": _provider_usage_value(evidence_provider, candidate, "llm_cache_status"),
                        "llm_cache_key": _provider_usage_value(evidence_provider, candidate, "llm_cache_key"),
                        "ocr_page_quality": _page_quality_for_result(document_ir, candidate),
                    },
                }
            )
            validated = validate_candidate(candidate, field, document_ir)
            if field.key in rule_shortcut_candidates:
                validated = validated.model_copy(update={"acceptance_reason": "rule_pre_accepted"})
            results_by_key[field.key] = validated
    finally:
        case_index.close()
    return [results_by_key[field.key] for field in schema.fields if field.key in results_by_key]


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


# ---------------------------------------------------------------------------
# Sync pipeline entry point
# ---------------------------------------------------------------------------


def _extract_document_evidence_first(
    document_ir: DocumentIR,
    *,
    provider: SemanticExtractionProvider,
    schema,
    trace: ProcessingTrace | None = None,
) -> list[ValidatedFieldResult]:
    phase_one_fields = [field for field in schema.fields if field.phase == 1]
    rule_shortcut_candidates, llm_fields = _partition_rule_shortcut_fields(
        schema, phase_one_fields, document_ir.blocks
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
        candidates = _error_fallback_candidates(llm_fields, exc, async_mode=False)

    candidates_by_key = {candidate.field_key: candidate for candidate in candidates}
    return _build_validated_results(
        phase_one_fields,
        candidates_by_key,
        rule_shortcut_candidates,
        evidence_provider,
        document_ir,
        context,
        schema,
        document_ir.blocks,
        extraction_strategy="evidence_first_multimodal",
    )


# ---------------------------------------------------------------------------
# Async pipeline entry point (S2-002)
# ---------------------------------------------------------------------------


async def _async_extract_document_evidence_first(
    document_ir: DocumentIR,
    *,
    provider: SemanticExtractionProvider,
    schema,
    trace: ProcessingTrace | None = None,
) -> list[ValidatedFieldResult]:
    """Async version of _extract_document_evidence_first.

    Uses provider.async_collect_evidence() for non-blocking LLM calls.
    All other steps remain synchronous (they are local/fast operations).
    Tracing is skipped in the async path to avoid DB commits in async context.
    """
    phase_one_fields = [field for field in schema.fields if field.phase == 1]
    rule_shortcut_candidates, llm_fields = _partition_rule_shortcut_fields(
        schema, phase_one_fields, document_ir.blocks
    )

    context = build_document_context(document_ir)
    online_allowed = document_ir.metadata.get("deidentification", {}).get("online_llm_allowed", True)
    evidence_provider = provider if online_allowed else ConservativeLocalProvider()

    try:
        evidence_by_field = await evidence_provider.async_collect_evidence(
            document_context=context, fields=llm_fields
        )
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
        logger.exception("Async evidence-first extraction failed for %s", document_ir.document_id)
        candidates = _error_fallback_candidates(llm_fields, exc, async_mode=True)

    candidates_by_key = {candidate.field_key: candidate for candidate in candidates}
    return _build_validated_results(
        phase_one_fields,
        candidates_by_key,
        rule_shortcut_candidates,
        evidence_provider,
        document_ir,
        context,
        schema,
        document_ir.blocks,
        extraction_strategy="evidence_first_multimodal_async",
    )
