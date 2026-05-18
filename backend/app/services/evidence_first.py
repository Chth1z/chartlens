from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from app.domain.models import (
    DocumentContext,
    DocumentIRBlock,
    EvidenceCandidate,
    ExtractedFact,
    ExtractionCandidate,
    FieldDecision,
    FieldDefinition,
)


NEGATION_TERMS = ("否认", "无", "未见", "未诉", "无明显", "无特殊")
UNCERTAIN_TERMS = ("?", "？", "待排", "疑似", "考虑", "可能")
SENTENCE_TERMINATORS = ("。", "；", ";", "\n")
FAMILY_SECTIONS = {"家族史", "婚育史"}
FAMILY_CONTEXT_PATTERN = re.compile(
    r"(?:家族史|婚育史|其父|其母|父亲|母亲|父母|家属|配偶|兄弟|姐妹|祖父|祖母|外祖父|外祖母|孕期|妊娠期|"
    r"[一二三四五六七八九两0-9]+[子女]|儿子|女儿)"
)


def collect_local_evidence(
    context: DocumentContext,
    fields: list[FieldDefinition],
) -> dict[str, list[EvidenceCandidate]]:
    evidence: dict[str, list[EvidenceCandidate]] = {field.key: [] for field in fields}
    blocks = [block for page in context.pages for block in page.blocks]
    for field in fields:
        candidates = []
        candidates.extend(_rule_pattern_evidence(field, blocks))
        candidates.extend(_fact_then_code_evidence(field, blocks))
        candidates.extend(_binary_history_evidence(field, blocks))
        candidates.extend(_implicit_negative_evidence(field, blocks))
        deduped = _dedupe_candidates(candidates)
        if deduped:
            selected = _select_candidate(field, deduped)
            evidence[field.key] = [selected, *[candidate for candidate in deduped if candidate != selected]]
        else:
            evidence[field.key] = []
    return evidence


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


def _candidate(
    *,
    field: FieldDefinition,
    block: DocumentIRBlock,
    raw_value: str | None,
    normalized_code: str | None,
    evidence_text: str,
    source_type: str,
    confidence: float,
    field_label_seen: str | None = None,
) -> EvidenceCandidate:
    return EvidenceCandidate(
        field_key=field.key,
        candidate_value=raw_value,
        normalized_code=normalized_code,
        block_id=block.block_id,
        block_ids=[block.block_id],
        text=block.text,
        evidence_text=evidence_text,
        page=block.page,
        bbox=block.bbox,
        confidence=confidence,
        ocr_confidence=block.confidence,
        score=confidence,
        section_label=block.section_label,
        document_kind=block.document_kind,
        source_type=source_type,
        field_label_seen=field_label_seen,
        document_region=block.document_region or block.section_label,
        visual_confirmed=False,
        family_context=_is_family_context(block),
        match_terms=[term for term in field.synonyms if term and term in evidence_text],
        context_text=block.text,
    )


def _apply_forbidden_context(
    field: FieldDefinition,
    block: DocumentIRBlock,
    candidate: EvidenceCandidate,
) -> EvidenceCandidate:
    flags = list(candidate.forbidden_inference_flags)
    if "family_context" in field.evidence_policy.forbidden_inference_sources and _is_family_context(block):
        flags.append("family_context")
    context_text = _candidate_context_text(block.text, candidate.evidence_text)
    if "family_context" in field.evidence_policy.forbidden_inference_sources and FAMILY_CONTEXT_PATTERN.search(context_text):
        flags.append("family_context")
    return candidate.model_copy(update={"forbidden_inference_flags": list(dict.fromkeys(flags))})


def _is_family_context(block: DocumentIRBlock) -> bool:
    if block.section_label in FAMILY_SECTIONS:
        return True
    return bool(re.search(r"(?:^|[。；;\n])(?:家族史|婚育史)\s*[:：]", block.text))


def _candidate_context_text(block_text: str, evidence_text: str | None) -> str:
    if not evidence_text:
        return block_text[:160]
    index = block_text.find(evidence_text)
    if index < 0:
        return evidence_text
    start = max(0, index - 24)
    end = min(len(block_text), index + len(evidence_text) + 24)
    return block_text[start:end]


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


def _source_type(block: DocumentIRBlock) -> str:
    if "layout_key_value_pair" in block.quality_flags:
        return "layout_key_value"
    if block.block_type in {"cell", "table"}:
        return "layout_cell"
    if block.block_type in {"form_field", "key_value", "checkbox", "selection_mark"}:
        return "form_field"
    return "ocr_text"


def _match_group(match: re.Match, group: int | str) -> str | None:
    try:
        return match.group(group)
    except Exception:
        return None


def _normalize_rule_value(raw_value: str | None, rule) -> str | None:
    if raw_value is None:
        return rule.normalized_code
    if rule.code_map:
        return rule.code_map.get(raw_value, rule.code_map.get(raw_value.strip()))
    return rule.normalized_code or raw_value


def _field_label_seen(field: FieldDefinition, evidence_text: str) -> str | None:
    for synonym in field.synonyms:
        if synonym and synonym in evidence_text:
            return synonym
    return None


def _negative_span(text: str, term: str, negation_terms: list[str]) -> str | None:
    negation_terms = [re.escape(term) for term in dict.fromkeys(negation_terms) if term]
    if not negation_terms:
        return None
    pattern = re.compile(rf"({'|'.join(negation_terms)})[^。；;\n]{{0,50}}{re.escape(term)}[^。；;\n]{{0,20}}")
    match = pattern.search(text)
    return _trim_span(match.group(0)) if match else None


def _positive_span(text: str, term: str) -> str | None:
    for match in re.finditer(re.escape(term), text):
        # Clip the span at sentence terminators on both sides so negations or
        # uncertainty markers that belong to a neighboring field in the next
        # clause cannot contaminate the positive evidence for this term.
        left_start = max(0, match.start() - 12)
        right_end = min(len(text), match.end() + 24)
        left_text = text[left_start:match.start()]
        for terminator in SENTENCE_TERMINATORS:
            idx = left_text.rfind(terminator)
            if idx != -1:
                left_start = left_start + idx + 1
                left_text = text[left_start:match.start()]
        right_text = text[match.end():right_end]
        for terminator in SENTENCE_TERMINATORS:
            idx = right_text.find(terminator)
            if idx != -1:
                right_end = match.end() + idx
                break
        # Negation that appears AFTER the term belongs to the next clause and
        # is handled by `_negative_span` against that clause's term. Only the
        # left context can negate the current occurrence.
        if any(negation in left_text for negation in NEGATION_TERMS):
            continue
        return _trim_span(text[left_start:right_end])
    return None


def _section_complete_negative_span(text: str) -> str | None:
    for pattern in (
        r"(?:既往史|个人史|系统回顾|病史)[：:]?\s*(?:无特殊|无明显异常|未见异常)",
        r"(?:余|其他)[^。；;\n]{0,12}(?:无特殊|无异常|未见异常)",
    ):
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return None


def _contains_uncertain(text: str) -> bool:
    return any(term in text for term in UNCERTAIN_TERMS)


def _trim_span(text: str) -> str:
    return text.strip(" ，,。；;\n\t")


def _candidate_confidence(candidate: EvidenceCandidate) -> float:
    return max(candidate.confidence, candidate.score, candidate.ocr_confidence)


def _dedupe_candidates(candidates: list[EvidenceCandidate]) -> list[EvidenceCandidate]:
    deduped: dict[tuple[str, str, str | None], EvidenceCandidate] = {}
    for candidate in candidates:
        key = (candidate.block_id, candidate.evidence_text or candidate.text, candidate.normalized_code)
        current = deduped.get(key)
        if current is None or _candidate_confidence(candidate) > _candidate_confidence(current):
            deduped[key] = candidate
    return list(deduped.values())
