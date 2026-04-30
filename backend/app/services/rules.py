from __future__ import annotations

import re

from app.domain.models import DocumentIRBlock, ExtractionCandidate, FieldDefinition


def rule_shortcut_extract(field: FieldDefinition, blocks: list[DocumentIRBlock]) -> ExtractionCandidate | None:
    configured = _extract_by_rule_patterns(field, blocks)
    if configured is not None:
        return configured
    if field.key == "gender":
        return _extract_gender(field, blocks)
    if field.key == "age":
        return _extract_age(field, blocks)
    if field.key == "hospital":
        return _extract_hospital(field, blocks)
    return None


def _extract_by_rule_patterns(field: FieldDefinition, blocks: list[DocumentIRBlock]) -> ExtractionCandidate | None:
    for rule in field.rule_patterns:
        try:
            pattern = re.compile(rule.pattern)
        except re.error:
            continue
        for block in blocks:
            if block.section_label in field.excluded_sections:
                continue
            match = pattern.search(block.text)
            if not match:
                continue
            raw_value = _match_group(match, rule.raw_group) or match.group(0)
            evidence_span = _match_group(match, rule.evidence_group) or match.group(0)
            normalized = rule.normalized_code or rule.code_map.get(raw_value, raw_value)
            confidence = rule.confidence
            if field.key == "age" and normalized.isdigit() and not 0 <= int(normalized) <= 120:
                confidence = min(confidence, 0.4)
            return _candidate(
                field,
                block,
                raw_value,
                normalized,
                evidence_span,
                confidence,
                rule.summary or "配置规则模式命中",
            )
    return None


def _match_group(match: re.Match, group: int | str) -> str | None:
    try:
        value = match.group(group)
    except (IndexError, KeyError):
        return None
    return str(value) if value is not None else None


def code_from_map(field: FieldDefinition, text: str) -> str | None:
    for code, terms in field.code_map.items():
        for term in terms:
            if term and term in text:
                return code
    return None


def _extract_gender(field: FieldDefinition, blocks: list[DocumentIRBlock]) -> ExtractionCandidate | None:
    patterns = [
        re.compile(r"(?:性别\s*[:：]?\s*)?(男|女)(?=$|[，,；;\s])"),
        re.compile(r"患者[，,]\s*(男|女)[，,]\s*\d{1,3}\s*岁"),
    ]
    for block in blocks:
        for pattern in patterns:
            match = pattern.search(block.text)
            if match:
                raw = match.group(1)
                return _candidate(field, block, raw, {"男": "1", "女": "2"}[raw], match.group(0), 0.96, "人口学强模式命中")
    return None


def _extract_age(field: FieldDefinition, blocks: list[DocumentIRBlock]) -> ExtractionCandidate | None:
    patterns = [
        re.compile(r"年龄\s*[:：]?\s*(\d{1,3})\s*岁"),
        re.compile(r"患者[，,]\s*(?:男|女)[，,]\s*(\d{1,3})\s*岁"),
    ]
    for block in blocks:
        for pattern in patterns:
            match = pattern.search(block.text)
            if not match:
                continue
            age = int(match.group(1))
            confidence = 0.96 if 0 <= age <= 120 else 0.4
            return _candidate(field, block, str(age), str(age), match.group(0), confidence, "年龄强模式命中")
    return None


def _extract_hospital(field: FieldDefinition, blocks: list[DocumentIRBlock]) -> ExtractionCandidate | None:
    pattern = re.compile(r"([\u4e00-\u9fffA-Za-z0-9（）()·\-]{2,50}医院)")
    for block in blocks:
        match = pattern.search(block.text)
        if match:
            return _candidate(field, block, match.group(1), match.group(1), match.group(1), 0.88, "医院名称强模式命中")
    return None


def _candidate(
    field: FieldDefinition,
    block: DocumentIRBlock,
    raw_value: str,
    normalized_code: str,
    evidence_span: str,
    confidence: float,
    summary: str,
) -> ExtractionCandidate:
    return ExtractionCandidate(
        field_key=field.key,
        field_group_key=field.field_group_key,
        raw_value=raw_value,
        normalized_code=normalized_code,
        status="confirmed",
        confidence=confidence,
        evidence_text=block.text,
        evidence_span=evidence_span,
        evidence_block_id=block.block_id,
        evidence_type="explicit_positive",
        page=block.page,
        bbox=block.bbox,
        reasoning_summary=summary,
        review_required=confidence < 0.9,
    )
