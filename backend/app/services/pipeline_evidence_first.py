from __future__ import annotations

import logging
import time

from app.domain.models import DocumentIR, ExtractionCandidate, ValidatedFieldResult
from app.services.document_context import build_document_context
from app.services.evidence_first import decisions_to_extraction_candidates
from app.services.evidence import (
    blocks_for_group,
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
    # M1-002: build the FTS5 evidence-search index once per case and reuse
    # it across every `build_evidence_packs` / `evidence_for_field` call
    # below. Without the index each call rebuilds the in-memory FTS table
    # (~22 fields per case for mock_general). Behavior is byte-identical;
    # only the per-call sqlite3 connection cost is amortized.
    case_index = build_evidence_index(all_blocks)
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
    finally:
        case_index.close()
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


# ---------------------------------------------------------------------------
# Async pipeline path (S2-002)
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

    # Rule shortcut (sync, fast) - same logic as sync version
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
                    "decision_status": "PASS",
                },
            }
        )

    context = build_document_context(document_ir)
    online_allowed = document_ir.metadata.get("deidentification", {}).get("online_llm_allowed", True)
    evidence_provider = provider if online_allowed else ConservativeLocalProvider()
    results_by_key: dict[str, ValidatedFieldResult] = {}

    try:
        # KEY ASYNC CALL: use async_collect_evidence for non-blocking LLM
        evidence_by_field = await evidence_provider.async_collect_evidence(
            document_context=context, fields=llm_fields
        )
        # Adjudication and verification are local/fast - run sync
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
        candidates = [
            ExtractionCandidate(
                field_key=field.key,
                field_group_key=field.field_group_key,
                normalized_code="unknown",
                status="error",
                evidence_type="no_evidence",
                reasoning_summary="异步证据优先抽取链路失败，字段降级进入人工复核。",
                review_required=True,
                error_code=f"ASYNC_EVIDENCE_FIRST_FAILED: {exc}",
                risk_level="high",
                provenance={"source": "evidence_first", "route": "async_failed"},
            )
            for field in llm_fields
        ]

    candidates_by_key = {candidate.field_key: candidate for candidate in candidates}
    candidates_by_key.update(rule_shortcut_candidates)
    all_blocks = document_ir.blocks
    case_index = build_evidence_index(all_blocks)
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
                        "extraction_strategy": "evidence_first_multimodal_async",
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
