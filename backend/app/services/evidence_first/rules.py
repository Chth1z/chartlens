from __future__ import annotations

import re

from app.domain.models import (
    DocumentIRBlock,
    EvidenceCandidate,
    FieldDefinition,
)

from app.services.evidence_first.candidates import (
    _apply_forbidden_context,
    _candidate,
    _candidate_confidence,
    _field_label_seen,
    _source_type,
)
from app.services.evidence_first.spans import (
    NEGATION_TERMS,
    _contains_uncertain,
    _match_group,
    _negative_span,
    _normalize_rule_value,
    _positive_span,
    _section_complete_negative_span,
)


def _rule_pattern_evidence(field: FieldDefinition, blocks: list[DocumentIRBlock]) -> list[EvidenceCandidate]:
    candidates: list[EvidenceCandidate] = []
    for block in blocks:
        if block.section_label in field.excluded_sections:
            continue
        for rule in field.rule_patterns:
            try:
                pattern = re.compile(rule.pattern)
            except re.error:
                continue
            for match in pattern.finditer(block.text):
                raw_value = _match_group(match, rule.raw_group)
                evidence_text = _match_group(match, rule.evidence_group) or match.group(0)
                normalized = _normalize_rule_value(raw_value, rule)
                if normalized is None:
                    normalized = raw_value
                candidate = _candidate(
                    field=field,
                    block=block,
                    raw_value=raw_value,
                    normalized_code=normalized,
                    evidence_text=evidence_text,
                    source_type=_source_type(block),
                    confidence=rule.confidence,
                    field_label_seen=_field_label_seen(field, evidence_text),
                )
                candidates.append(_apply_forbidden_context(field, block, candidate))
    return candidates


def _binary_history_evidence(field: FieldDefinition, blocks: list[DocumentIRBlock]) -> list[EvidenceCandidate]:
    if not {"1", "0"}.issubset(set(field.allowed_codes)):
        return []
    # Score and imaging fields have their own dedicated evidence path
    # (_fact_then_code_evidence → _recorded_or_derived_score_evidence).
    # Running binary-history matching on them produces spurious candidates
    # (e.g., 'mRS' synonym triggers code=1 that conflicts with the correct
    # score value). Skip them here.
    if field.extract_mode in {"computed_from_facts", "fact_then_code"}:
        return []
    # Discharge-outcome fields (in_hospital_death, transfer) have inverted
    # negation semantics: their synonyms include both positive indicators
    # (死亡, 转院) and outcome-negation indicators (好转, 未转诊) that the
    # simple positive/negative synonym matching cannot handle correctly.
    # These fields are designed for LLM extraction; skip binary-history here.
    if field.field_group_key == "discharge_group":
        return []
    candidates: list[EvidenceCandidate] = []
    positive_terms = [term for term in field.synonyms if term and term not in {"男", "女"}]
    if not positive_terms:
        return []
    for block in blocks:
        if block.section_label in field.excluded_sections:
            continue
        for term in positive_terms:
            negative_span = _negative_span(block.text, term, [*field.negation_terms, *NEGATION_TERMS])
            if negative_span:
                candidate = _candidate(
                    field=field,
                    block=block,
                    raw_value="无",
                    normalized_code="0",
                    evidence_text=negative_span,
                    source_type=_source_type(block),
                    confidence=0.92,
                    field_label_seen=term,
                )
                candidates.append(_apply_forbidden_context(field, block, candidate))
                continue
            positive_span = _positive_span(block.text, term)
            if positive_span and not _contains_uncertain(positive_span):
                candidate = _candidate(
                    field=field,
                    block=block,
                    raw_value="有",
                    normalized_code="1",
                    evidence_text=positive_span,
                    source_type=_source_type(block),
                    confidence=0.88,
                    field_label_seen=term,
                )
                candidates.append(_apply_forbidden_context(field, block, candidate))
    return candidates


def _implicit_negative_evidence(field: FieldDefinition, blocks: list[DocumentIRBlock]) -> list[EvidenceCandidate]:
    if field.evidence_policy.implicit_negative_policy != "section_complete_only":
        return []
    if not {"1", "0"}.issubset(set(field.allowed_codes)):
        return []
    candidates: list[EvidenceCandidate] = []
    for block in blocks:
        if block.section_label in field.excluded_sections:
            continue
        if block.section_label not in field.source_sections:
            continue
        span = _section_complete_negative_span(block.text)
        if not span:
            continue
        candidates.append(
            _candidate(
                field=field,
                block=block,
                raw_value="无",
                normalized_code="0",
                evidence_text=span,
                source_type="implicit_negative",
                confidence=0.78,
                field_label_seen=block.section_label,
            )
        )
    return candidates


def _fact_then_code_evidence(field: FieldDefinition, blocks: list[DocumentIRBlock]) -> list[EvidenceCandidate]:
    if field.extract_mode not in {"fact_then_code", "computed_from_facts"}:
        return []
    score_candidate = _recorded_or_derived_score_evidence(field, blocks)
    if score_candidate is not None:
        return [score_candidate]

    matches: list[EvidenceCandidate] = []
    for block in blocks:
        if block.section_label in field.excluded_sections:
            continue
        if field.source_sections and block.section_label not in field.source_sections:
            continue
        for code, terms in field.code_map.items():
            for term in terms:
                if term and term in block.text:
                    matches.append(
                        _candidate(
                            field=field,
                            block=block,
                            raw_value=term,
                            normalized_code=code,
                            evidence_text=term,
                            source_type=_source_type(block),
                            confidence=0.9,
                            field_label_seen=term,
                        ).model_copy(update={"score_reason": "event_fact"})
                    )
    if not matches:
        return []
    return [max(matches, key=lambda item: (_candidate_confidence(item), len(item.evidence_text or "")))]


def _recorded_or_derived_score_evidence(field: FieldDefinition, blocks: list[DocumentIRBlock]) -> EvidenceCandidate | None:
    labels = {
        "hh_grade": r"(?:HH|Hunt[-\s]?Hess)\s*(?:分级|评分|级)?\s*[:：]?\s*([1-5ⅠⅡⅢⅣⅤ])",
        "wfns_grade": r"WFNS\s*(?:分级|评分|级)?\s*[:：]?\s*([1-5ⅠⅡⅢⅣⅤ])",
        "fisher_grade": r"Fisher\s*(?:分级|评分|级)?\s*[:：]?\s*([1-4ⅠⅡⅢⅣ])",
        "mrs_score": r"(?:mRS|MRS|改良Rankin)\s*(?:评分|分)?\s*[:：]?\s*([0-6])",
    }
    pattern_text = labels.get(field.key)
    roman = {"Ⅰ": "1", "Ⅱ": "2", "Ⅲ": "3", "Ⅳ": "4", "Ⅴ": "5"}
    if pattern_text:
        pattern = re.compile(pattern_text, re.IGNORECASE)
        for block in blocks:
            if field.source_sections and block.section_label not in field.source_sections:
                continue
            match = pattern.search(block.text)
            if not match:
                continue
            code = roman.get(match.group(1), match.group(1))
            return _candidate(
                field=field,
                block=block,
                raw_value=code,
                normalized_code=code,
                evidence_text=match.group(0),
                source_type=_source_type(block),
                confidence=0.92,
                field_label_seen=field.key,
            ).model_copy(update={"score_reason": "explicit_recorded_score"})
    if field.key == "wfns_grade":
        gcs = _extract_gcs(blocks, field)
        if gcs:
            block, span, score = gcs
            derived = "1" if score == 15 else "2" if 13 <= score <= 14 else "4" if 7 <= score <= 12 else "5"
            return _candidate(
                field=field,
                block=block,
                raw_value=derived,
                normalized_code=derived,
                evidence_text=span,
                source_type="derived",
                confidence=0.65,
                field_label_seen="GCS",
            ).model_copy(update={"score_reason": "derived_from_gcs"})
    return None


def _extract_gcs(blocks: list[DocumentIRBlock], field: FieldDefinition) -> tuple[DocumentIRBlock, str, int] | None:
    pattern = re.compile(r"GCS\s*[:：]?\s*(\d{1,2})")
    for block in blocks:
        if field.source_sections and block.section_label not in field.source_sections:
            continue
        match = pattern.search(block.text)
        if match:
            return block, match.group(0), int(match.group(1))
    return None
