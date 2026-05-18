from __future__ import annotations

from app.domain.models import (
    EvidenceCandidate,
    ExtractedFact,
    ExtractionCandidate,
    FieldDecision,
    FieldDefinition,
)

from app.services.evidence_first.candidates import _candidate_confidence


def adjudicate_field_decisions(
    fields: list[FieldDefinition],
    evidence_by_field: dict[str, list[EvidenceCandidate]],
) -> dict[str, FieldDecision]:
    decisions: dict[str, FieldDecision] = {}
    for field in fields:
        candidates = evidence_by_field.get(field.key, [])
        usable = [candidate for candidate in candidates if not candidate.forbidden_inference_flags]
        if not usable:
            decisions[field.key] = FieldDecision(
                field_key=field.key,
                decision_status="MISSING",
                normalized_code="unknown",
                rejected_candidates=candidates,
                reasoning_summary="未找到符合字段证据政策的候选证据。",
                needs_human_review=True,
                review_reasons=["missing_evidence"],
            )
            continue

        normalized_values = {
            candidate.normalized_code
            for candidate in usable
            if candidate.normalized_code not in (None, "unknown")
        }
        if len(normalized_values) > 1 and field.evidence_policy.conflict_policy == "review_conflict":
            decisions[field.key] = FieldDecision(
                field_key=field.key,
                decision_status="CONFLICT",
                normalized_code="unknown",
                conflict_candidates=usable,
                rejected_candidates=[candidate for candidate in candidates if candidate not in usable],
                reasoning_summary="同一字段存在多个互相冲突的候选证据，进入人工复核。",
                needs_human_review=True,
                review_reasons=["conflicting_evidence"],
            )
            continue

        selected = _select_candidate(field, usable)
        review_reasons = _review_reasons(field, selected)
        decision_status = "REVIEW" if review_reasons else "PASS"
        decisions[field.key] = FieldDecision(
            field_key=field.key,
            decision_status=decision_status,
            raw_value=selected.candidate_value or selected.evidence_text or selected.text,
            normalized_code=selected.normalized_code or "unknown",
            confidence=_candidate_confidence(selected),
            selected_candidate=selected,
            rejected_candidates=[candidate for candidate in candidates if candidate != selected],
            reasoning_summary=_decision_summary(field, selected, review_reasons),
            needs_human_review=bool(review_reasons),
            forbidden_inference_used=bool(selected.forbidden_inference_flags),
            pass_reasons=[] if review_reasons else ["explicit_evidence", "allowed_code", "no_conflict"],
            review_reasons=review_reasons,
        )
    return decisions


def decisions_to_extraction_candidates(
    fields: list[FieldDefinition],
    decisions_by_field: dict[str, FieldDecision],
) -> list[ExtractionCandidate]:
    candidates: list[ExtractionCandidate] = []
    for field in fields:
        decision = decisions_by_field.get(field.key)
        if decision is None:
            candidates.append(_missing_candidate(field, "FIELD_DECISION_MISSING"))
            continue
        selected = decision.selected_candidate
        if selected is None or decision.normalized_code in (None, "unknown"):
            candidates.append(
                ExtractionCandidate(
                    field_key=field.key,
                    field_group_key=field.field_group_key,
                    normalized_code="unknown",
                    status="conflict" if decision.decision_status == "CONFLICT" else "not_mentioned",
                    confidence=decision.confidence,
                    evidence_type="conflict" if decision.decision_status == "CONFLICT" else "no_evidence",
                    evidence_candidates=[*decision.conflict_candidates, *decision.rejected_candidates],
                    reasoning_summary=decision.reasoning_summary,
                    review_required=True,
                    error_code="CONFLICT" if decision.decision_status == "CONFLICT" else "NOT_MENTIONED",
                    risk_level="high" if decision.decision_status == "CONFLICT" else "medium",
                    provenance={"source": "evidence_first_adjudication", "decision_status": decision.decision_status},
                )
            )
            continue
        derived = selected.source_type == "derived"
        fact_review_required = field.key in {"aneurysm_location", "surgery_method"}
        candidates.append(
            ExtractionCandidate(
                field_key=field.key,
                field_group_key=field.field_group_key,
                raw_value=decision.raw_value,
                normalized_code=decision.normalized_code,
                status="derived_candidate" if derived else "confirmed",
                confidence=decision.confidence,
                evidence_text=selected.evidence_text or selected.text,
                evidence_span=selected.evidence_text or selected.text,
                evidence_block_id=selected.block_id,
                evidence_type=_evidence_type(field, selected, decision.normalized_code),
                page=selected.page,
                bbox=selected.bbox,
                reasoning_summary=decision.reasoning_summary,
                review_required=decision.needs_human_review or derived or fact_review_required,
                error_code="DERIVED_REQUIRES_REVIEW" if derived else None,
                facts=_candidate_facts(field, selected),
                evidence_candidates=[selected, *decision.rejected_candidates],
                provenance={
                    "source": "evidence_first_adjudication",
                    "decision_status": decision.decision_status,
                    "source_type": selected.source_type,
                    "visual_confirmed": selected.visual_confirmed,
                    "review_reasons": decision.review_reasons,
                    "pass_reasons": decision.pass_reasons,
                },
                acceptance_reason=";".join(decision.pass_reasons or decision.review_reasons) or None,
                risk_level="medium" if decision.needs_human_review else "low",
            )
        )
    return candidates


def _select_candidate(field: FieldDefinition, candidates: list[EvidenceCandidate]) -> EvidenceCandidate:
    priority = field.evidence_policy.source_priority or field.evidence_priority

    def sort_key(candidate: EvidenceCandidate) -> tuple[int, float, float]:
        source_rank = _priority_rank(
            priority,
            candidate.source_type,
            candidate.document_region,
            candidate.section_label,
            candidate.field_label_seen,
        )
        return (source_rank, -_candidate_confidence(candidate), -candidate.ocr_confidence)

    return sorted(candidates, key=sort_key)[0]


def _priority_rank(priority: list[str], *values: str | None) -> int:
    if not priority:
        return 0
    joined = " ".join(value for value in values if value)
    for index, item in enumerate(priority):
        if item and item in joined:
            return index
    return len(priority)


def _review_reasons(field: FieldDefinition, candidate: EvidenceCandidate) -> list[str]:
    reasons: list[str] = []
    policy = field.evidence_policy
    if candidate.source_type not in policy.allowed_evidence_sources:
        reasons.append("source_type_not_allowed")
    if policy.allowed_document_regions and candidate.document_region not in policy.allowed_document_regions:
        reasons.append("document_region_not_allowed")
    if candidate.document_region in policy.forbidden_document_regions:
        reasons.append("document_region_forbidden")
    if candidate.forbidden_inference_flags:
        reasons.extend(candidate.forbidden_inference_flags)
    if policy.require_visual_confirmation and not candidate.visual_confirmed:
        reasons.append("visual_confirmation_missing")
    if candidate.normalized_code not in field.allowed_codes and not _generic_allowed(field, candidate.normalized_code):
        reasons.append("normalized_code_not_allowed")
    return list(dict.fromkeys(reasons))


def _generic_allowed(field: FieldDefinition, normalized_code: str | None) -> bool:
    if not normalized_code:
        return False
    return (
        ("text" in field.allowed_codes and normalized_code != "unknown")
        or ("integer" in field.allowed_codes and normalized_code.isdigit())
        or ("duration" in field.allowed_codes and normalized_code != "unknown")
    )


def _decision_summary(field: FieldDefinition, candidate: EvidenceCandidate, review_reasons: list[str]) -> str:
    if review_reasons:
        return f"证据优先仲裁命中 {field.label} 候选，但因 {', '.join(review_reasons)} 进入复核。"
    return f"证据优先仲裁命中 {field.label} 的明确证据。"


def _evidence_type(field: FieldDefinition, candidate: EvidenceCandidate, normalized_code: str | None):
    if candidate.source_type == "derived":
        return "derived"
    if field.extract_mode in {"fact_then_code", "computed_from_facts"}:
        return "event_fact" if candidate.score_reason != "explicit_recorded_score" else "explicit_recorded_score"
    if candidate.source_type == "implicit_negative":
        return "explicit_composite_negative"
    if normalized_code == "0":
        return "explicit_negative"
    return "explicit_positive"


def _candidate_facts(field: FieldDefinition, candidate: EvidenceCandidate) -> list[ExtractedFact]:
    if field.extract_mode not in {"fact_then_code", "computed_from_facts"}:
        return []
    evidence_text = candidate.evidence_text or candidate.text
    return [
        ExtractedFact(
            fact_type=field.key,
            raw_text=evidence_text,
            normalized=candidate.normalized_code,
            evidence_span=evidence_text,
            evidence_block_id=candidate.block_id,
            confidence=_candidate_confidence(candidate),
        )
    ]


def _missing_candidate(field: FieldDefinition, error_code: str) -> ExtractionCandidate:
    return ExtractionCandidate(
        field_key=field.key,
        field_group_key=field.field_group_key,
        normalized_code="unknown",
        status="not_mentioned",
        evidence_type="no_evidence",
        reasoning_summary="证据优先仲裁未返回字段决策。",
        review_required=True,
        error_code=error_code,
        provenance={"source": "evidence_first_adjudication"},
    )
