from __future__ import annotations

from typing import Protocol

from app.schemas.pipeline import EvidenceCandidate
from app.services.field_dictionary import FieldDefinition
from app.services.medical_dictionary import terms_for_field


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
    keywords = [field.label, *field.synonyms, *field.evidence_priority, *terms_for_field(field.key)]
    keywords = [keyword for keyword in keywords if keyword]
    max_items = limit or field.max_evidence_items

    for block in blocks:
        text = block.text.strip()
        if not text:
            continue
        matches = sum(1 for keyword in keywords if keyword in text)
        if matches == 0:
            continue
        excerpt = _trim_around_keywords(text, keywords, field.evidence_window_chars)
        section_name = str(getattr(block, "section_name", ""))
        section_bonus = 0.18 if section_name and section_name in field.source_sections else 0.0
        priority_bonus = 0.12 if any(term in text for term in field.evidence_priority) else 0.0
        score = min(1.0, matches / max(2, len(keywords[:8])) + block.confidence * 0.45 + section_bonus + priority_bonus)
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
