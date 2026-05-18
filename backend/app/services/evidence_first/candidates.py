from __future__ import annotations

import re

from app.domain.models import (
    DocumentIRBlock,
    EvidenceCandidate,
    FieldDefinition,
)


FAMILY_SECTIONS = {"家族史", "婚育史"}
FAMILY_CONTEXT_PATTERN = re.compile(
    r"(?:家族史|婚育史|其父|其母|父亲|母亲|父母|家属|配偶|兄弟|姐妹|祖父|祖母|外祖父|外祖母|孕期|妊娠期|"
    r"[一二三四五六七八九两0-9]+[子女]|儿子|女儿)"
)


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


def _source_type(block: DocumentIRBlock) -> str:
    if "layout_key_value_pair" in block.quality_flags:
        return "layout_key_value"
    if block.block_type in {"cell", "table"}:
        return "layout_cell"
    if block.block_type in {"form_field", "key_value", "checkbox", "selection_mark"}:
        return "form_field"
    return "ocr_text"


def _field_label_seen(field: FieldDefinition, evidence_text: str) -> str | None:
    for synonym in field.synonyms:
        if synonym and synonym in evidence_text:
            return synonym
    return None


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
