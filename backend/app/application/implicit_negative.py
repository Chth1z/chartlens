from __future__ import annotations

from app.domain.clinical import DocumentFragment, FieldExtractionResult
from app.domain.field_definitions import FieldDefinition
from app.application.medical_dictionary import terms_for_field

HISTORY_FIELDS = {
    "hypertension_history",
    "diabetes_history",
    "hyperlipidemia_history",
    "heart_disease_history",
    "stroke_history",
    "tumor_history",
}
PERSONAL_HISTORY_FIELDS = {"smoking_history", "drinking_history"}


def apply_implicit_negative(
    field: FieldDefinition,
    result: FieldExtractionResult,
    fragments: list[DocumentFragment],
    *,
    quality_band: str,
    history_terms: dict[str, list[str]] | None = None,
    unknown_terms: list[str] | None = None,
) -> FieldExtractionResult:
    if result.normalized_code not in (None, "unknown"):
        return result
    if quality_band == "poor":
        return result

    target_sections = _target_sections(field.key)
    if not target_sections:
        return result

    target_fragments = [
        fragment
        for fragment in fragments
        if fragment.block_type != "line" and fragment.section_name in target_sections and fragment.confidence >= 0.80
    ]
    if not target_fragments:
        return result

    combined_text = "\n".join(fragment.text for fragment in target_fragments)
    effective_unknown_terms = [*(unknown_terms or []), "未详", "不清", "记不清"]
    if any(term in combined_text for term in effective_unknown_terms):
        return result

    positive_terms = [term for term in terms_for_field(field.key, history_terms) + field.synonyms if term]
    if any(term in combined_text for term in positive_terms):
        return result

    evidence = min(target_fragments, key=lambda item: item.reading_order)
    return FieldExtractionResult(
        field_key=field.key,
        raw_value="无",
        normalized_code="0",
        confidence=0.86,
        evidence_text=_excerpt(evidence.text),
        page=evidence.page,
        bbox=evidence.bbox,
        reasoning_summary=f"隐式阴性：{','.join(target_sections)}章节存在，未见该字段阳性、不详或冲突线索，按科研录入规则置为无。",
        review_required=False,
        error_code=None,
    )


def _target_sections(field_key: str) -> list[str]:
    if field_key in HISTORY_FIELDS:
        return ["既往史"]
    if field_key in PERSONAL_HISTORY_FIELDS:
        return ["个人史", "生活史"]
    return []


def _excerpt(text: str, limit: int = 240) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[: limit - 3] + "..."
