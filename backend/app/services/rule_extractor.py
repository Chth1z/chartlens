from __future__ import annotations

import re
from typing import Any

from app.schemas.pipeline import EvidenceCandidate, FieldExtractionResult
from app.services.confidence import score_field_confidence
from app.services.field_dictionary import FieldDefinition


def extract_field_by_rules(
    field: FieldDefinition,
    evidence: list[EvidenceCandidate],
) -> FieldExtractionResult:
    if field.extract_mode == "manual":
        return _unknown(field, "RULE_DISABLED", "该字段在配置中设为人工/二期处理。")
    if not evidence:
        return _unknown(field, "NO_EVIDENCE", "未找到支持该字段的脱敏 OCR 证据。")

    strategy = field.rule_strategy or {"kind": "keyword"}
    kind = str(strategy.get("kind", "keyword"))
    if kind == "regex":
        result = _extract_regex(field, evidence, strategy)
    elif kind == "history":
        result = _extract_history(field, evidence, strategy)
    elif kind == "mapping":
        result = _extract_mapping(field, evidence, strategy)
    else:
        result = _extract_keyword(field, evidence)

    if result is None:
        return _unknown(field, "RULE_MISS", "规则未命中，需人工或模型复核。")
    return result


def should_escalate_to_llm(field: FieldDefinition, result: FieldExtractionResult) -> bool:
    if not field.llm.enabled:
        return False
    statuses = _result_statuses(result)
    return bool(set(field.llm.trigger_statuses).intersection(statuses))


def compact_evidence_for_llm(
    field: FieldDefinition,
    evidence: list[EvidenceCandidate],
    *,
    max_chars: int | None = None,
) -> list[EvidenceCandidate]:
    budget = max_chars if max_chars is not None else field.llm.evidence_budget
    compacted: list[EvidenceCandidate] = []
    remaining = max(0, budget)
    for item in evidence[: field.max_evidence_items]:
        if remaining <= 0:
            break
        text = item.text
        if len(text) > remaining:
            text = text[: max(0, remaining - 3)] + "..."
        compacted.append(item.model_copy(update={"text": text}))
        remaining -= len(text)
    return compacted


def _extract_regex(
    field: FieldDefinition,
    evidence: list[EvidenceCandidate],
    strategy: dict[str, Any],
) -> FieldExtractionResult | None:
    pattern = strategy.get("pattern")
    if not pattern:
        return None
    compiled = re.compile(str(pattern), re.IGNORECASE)
    value_map = {str(key): str(value) for key, value in (strategy.get("value_map") or {}).items()}
    for item in evidence:
        match = compiled.search(item.text)
        if not match:
            continue
        raw_value = str(match.group(1) if match.groups() else match.group(0)).strip()
        normalized = value_map.get(raw_value, raw_value)
        numeric_min = strategy.get("numeric_min")
        numeric_max = strategy.get("numeric_max")
        low_confidence_reason = None
        if numeric_min is not None or numeric_max is not None:
            try:
                numeric = float(raw_value)
                if numeric_min is not None and numeric < float(numeric_min):
                    low_confidence_reason = "数值低于配置范围。"
                if numeric_max is not None and numeric > float(numeric_max):
                    low_confidence_reason = "数值高于配置范围。"
            except ValueError:
                low_confidence_reason = "无法解析为数值。"
        return _scored_result(
            field,
            item,
            raw_value=raw_value,
            normalized_code=normalized,
            model_confidence=0.95 if low_confidence_reason is None else 0.55,
            reasoning_summary="配置正则直接命中字段证据。",
            review_required=low_confidence_reason is not None,
            error_code="LOW_CONFIDENCE" if low_confidence_reason else None,
        )
    return None


def _extract_history(
    field: FieldDefinition,
    evidence: list[EvidenceCandidate],
    strategy: dict[str, Any],
) -> FieldExtractionResult | None:
    unknown = _first_pattern(evidence, strategy.get("unknown_patterns") or [])
    negative = _first_pattern(evidence, strategy.get("negative_patterns") or field.negation_terms)
    positive = _first_pattern(evidence, strategy.get("positive_patterns") or field.synonyms)

    if positive and negative and positive.text != negative.text:
        return _scored_result(
            field,
            positive,
            raw_value="冲突",
            normalized_code="unknown",
            model_confidence=0.45,
            reasoning_summary="不同证据中同时出现肯定和否定线索。",
            review_required=True,
            error_code="CONFLICT",
            has_conflict=True,
        )
    if unknown:
        return _scored_result(
            field,
            unknown,
            raw_value="不详",
            normalized_code="unknown",
            model_confidence=0.70,
            reasoning_summary="证据明确提示病史不详。",
            review_required=True,
            error_code="UNKNOWN_EVIDENCE",
        )
    if negative:
        return _scored_result(
            field,
            negative,
            raw_value="无",
            normalized_code="0",
            model_confidence=0.88,
            reasoning_summary="证据中出现否定病史表达，按规则置为无并进入复核。",
            review_required=True,
            error_code="NEGATED_EVIDENCE_REVIEW",
        )
    if positive:
        return _scored_result(
            field,
            positive,
            raw_value="有",
            normalized_code="1",
            model_confidence=0.90,
            reasoning_summary="证据中出现肯定病史关键词。",
        )
    return None


def _extract_mapping(
    field: FieldDefinition,
    evidence: list[EvidenceCandidate],
    strategy: dict[str, Any],
) -> FieldExtractionResult | None:
    mapping = strategy.get("mapping") or {}
    if not isinstance(mapping, dict):
        return None
    for normalized_code, patterns in mapping.items():
        match = _first_pattern(evidence, patterns if isinstance(patterns, list) else [str(patterns)])
        if match:
            return _scored_result(
                field,
                match,
                raw_value=_matched_pattern(match.text, patterns) or str(normalized_code),
                normalized_code=str(normalized_code),
                model_confidence=0.88,
                reasoning_summary="配置映射词表命中字段证据。",
            )
    return None


def _extract_keyword(
    field: FieldDefinition,
    evidence: list[EvidenceCandidate],
) -> FieldExtractionResult | None:
    for item in evidence:
        for keyword in field.synonyms:
            if keyword in item.text:
                return _scored_result(
                    field,
                    item,
                    raw_value=keyword,
                    normalized_code=keyword if "text" in field.allowed_codes else "unknown",
                    model_confidence=0.70,
                    reasoning_summary="字段关键词命中，但未配置更具体的归一化规则。",
                    review_required=True,
                    error_code="LOW_CONFIDENCE",
                )
    return None


def _first_pattern(evidence: list[EvidenceCandidate], patterns: list[str]) -> EvidenceCandidate | None:
    for pattern in patterns:
        compiled = re.compile(str(pattern), re.IGNORECASE)
        for item in evidence:
            if compiled.search(item.text):
                return item
    return None


def _matched_pattern(text: str, patterns: object) -> str | None:
    if not isinstance(patterns, list):
        patterns = [str(patterns)]
    for pattern in patterns:
        match = re.search(str(pattern), text, re.IGNORECASE)
        if match:
            return match.group(0)
    return None


def _scored_result(
    field: FieldDefinition,
    evidence: EvidenceCandidate,
    *,
    raw_value: str,
    normalized_code: str,
    model_confidence: float,
    reasoning_summary: str,
    review_required: bool | None = None,
    error_code: str | None = None,
    has_conflict: bool = False,
) -> FieldExtractionResult:
    rule_consistent = _is_allowed(field, normalized_code)
    decision = score_field_confidence(
        model_confidence=model_confidence,
        ocr_confidence=evidence.ocr_confidence,
        evidence_strength=evidence.score,
        rule_consistent=rule_consistent,
        has_conflict=has_conflict,
        has_evidence=normalized_code != "unknown",
    )
    forced_review = bool(review_required)
    return FieldExtractionResult(
        field_key=field.key,
        raw_value=raw_value,
        normalized_code=normalized_code,
        confidence=round(decision.score, 4),
        evidence_text=evidence.text,
        page=evidence.page,
        bbox=evidence.bbox,
        reasoning_summary=reasoning_summary,
        review_required=forced_review or decision.review_required,
        error_code=error_code if (forced_review or decision.review_required or normalized_code == "unknown") else None,
    )


def _unknown(field: FieldDefinition, error_code: str, summary: str) -> FieldExtractionResult:
    return FieldExtractionResult(
        field_key=field.key,
        raw_value=None,
        normalized_code="unknown",
        confidence=0.0,
        evidence_text=None,
        page=None,
        bbox=[],
        reasoning_summary=summary,
        review_required=True,
        error_code=error_code,
    )


def _is_allowed(field: FieldDefinition, normalized_code: str) -> bool:
    if normalized_code in field.allowed_codes:
        return True
    return ("text" in field.allowed_codes and normalized_code != "unknown") or (
        "integer" in field.allowed_codes and normalized_code.isdigit()
    )


def _result_statuses(result: FieldExtractionResult) -> set[str]:
    statuses: set[str] = set()
    if result.normalized_code in (None, "unknown"):
        statuses.add("missing")
    if result.error_code == "CONFLICT":
        statuses.add("conflict")
    if result.error_code in {"LOW_CONFIDENCE", "NEGATED_EVIDENCE_REVIEW", "UNKNOWN_EVIDENCE"}:
        statuses.add("low_confidence")
    if result.review_required:
        statuses.add("needs_review")
    return statuses
