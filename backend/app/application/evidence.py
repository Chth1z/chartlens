from __future__ import annotations

import re
from typing import Protocol

from app.domain.clinical import EvidenceCandidate
from app.domain.field_definitions import FieldDefinition
from app.application.medical_dictionary import terms_for_field


_FORM_FOLLOWING_LABELS = (
    "姓名|性别|年龄|住址|民族|婚姻|职业|工作单位|联系人|病史陈述人|可靠程度|入院日期|记录日期|出院日期|入院时间|出院时间"
)
_DEMOGRAPHIC_EVIDENCE_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "gender": [
        re.compile(rf"(?:^|[:：，,；;\s])性别\s*[:：]?\s*(男|女)(?=$|[，,；;\s]|{_FORM_FOLLOWING_LABELS})"),
        re.compile(r"患者[，,]\s*(男|女)[，,]\s*\d{1,3}\s*岁"),
    ],
    "age": [
        re.compile(rf"(?:^|[:：，,；;\s])年龄\s*[:：]?\s*(\d{{1,3}})\s*岁(?=$|[，,；;\s]|{_FORM_FOLLOWING_LABELS})"),
        re.compile(rf"(?:^|[:：，,；;\s])年龄\s*[:：]?\s*[^，,；;\s]{{1,16}}(?=$|[，,；;\s]|{_FORM_FOLLOWING_LABELS})"),
        re.compile(r"患者[，,]\s*(?:男|女)[，,]\s*(\d{1,3})\s*岁"),
    ],
}


class TextBlock(Protocol):
    page: int
    text: str
    bbox: list[float]
    confidence: float


def retrieve_evidence(
    field: FieldDefinition,
    blocks: list[TextBlock],
    *,
    limit: int | None = None,
) -> list[EvidenceCandidate]:
    candidates: list[EvidenceCandidate] = []
    demographic_patterns = _DEMOGRAPHIC_EVIDENCE_PATTERNS.get(field.key)
    keywords = _keywords_for_field(field)
    keywords = [keyword for keyword in keywords if keyword]
    max_items = limit or field.max_evidence_items

    for block in blocks:
        text = block.text.strip()
        if not text:
            continue
        section_name = str(getattr(block, "section_name", ""))
        if section_name and section_name in field.excluded_sections:
            continue
        if demographic_patterns is not None and not _matches_any(text, demographic_patterns):
            continue
        matches = _match_count(text, keywords)
        if demographic_patterns is not None and matches == 0:
            matches = 1
        if matches == 0:
            continue
        excerpt = _trim_around_keywords(text, keywords, field.evidence_window_chars)
        source_section_match = bool(section_name and section_name in field.source_sections)
        section_bonus = 0.30 if source_section_match else 0.0
        block_type = str(getattr(block, "block_type", "paragraph"))
        form_bonus = 0.35 if block_type == "form_field" else 0.0
        priority_bonus = 0.12 if any(term in text for term in field.evidence_priority) else 0.0
        non_source_penalty = 0.08 if section_name and field.source_sections and not source_section_match else 0.0
        score = min(
            1.0,
            matches / max(2, len(keywords[:8]))
            + block.confidence * 0.45
            + section_bonus
            + form_bonus
            + priority_bonus
            - non_source_penalty,
        )
        candidates.append(
            EvidenceCandidate(
                field_key=field.key,
                text=excerpt,
                page=block.page,
                bbox=block.bbox,
                ocr_confidence=block.confidence,
                score=score,
            )
        )

    candidates.sort(key=lambda item: (item.score, item.ocr_confidence), reverse=True)
    return candidates[:max_items]


def _keywords_for_field(field: FieldDefinition) -> list[str]:
    if field.key in _DEMOGRAPHIC_EVIDENCE_PATTERNS:
        return [field.label, *field.evidence_priority]
    return [field.label, *field.synonyms, *field.evidence_priority, *terms_for_field(field.key)]


def _matches_any(text: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _match_count(text: str, keywords: list[str]) -> int:
    return sum(1 for keyword in keywords if keyword in text)


def _trim_around_keywords(text: str, keywords: list[str], max_chars: int) -> str:
    if len(text) <= max_chars:
        return text

    indexes = [text.find(keyword) for keyword in keywords if keyword and text.find(keyword) >= 0]
    center = min(indexes) if indexes else 0
    half = max_chars // 2
    start = max(0, center - half)
    end = min(len(text), start + max_chars)
    start = max(0, end - max_chars)
    excerpt = text[start:end]
    if start > 0:
        excerpt = "..." + excerpt[3:]
    if end < len(text):
        excerpt = excerpt[:-3] + "..."
    return excerpt
