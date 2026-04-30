from __future__ import annotations

from app.domain.models import DocumentProfile


DEFAULT_EXTRACTION_SYSTEM_PROMPT = (
    "You extract structured fields from de-identified documents. "
    "Return evidence-grounded candidates only. Missing means unknown, never negative."
)

DEFAULT_EXTRACTION_RULES = [
    "Only use the supplied de-identified evidence_packs.",
    "Do not infer absent information. If a fact is not explicitly mentioned, return normalized_code='unknown'.",
    "A non-unknown result must include evidence_span and evidence_block_id.",
    "evidence_span must be copied verbatim from the referenced block text.",
    "If there is contradiction, return normalized_code='unknown', status='conflict', evidence_type='conflict', review_required=true.",
]

DEFAULT_DOCUMENT_AI_PROMPT = (
    "You are an intelligent document parsing engine. Extract visible text, table cells, form fields, and selection marks. "
    "Return strict JSON only, without Markdown or explanation. "
    "JSON schema: {\"blocks\":[{\"page\":1,\"reading_order\":1,\"text\":\"...\","
    "\"bbox\":[x1,y1,x2,y2],\"confidence\":0.0,"
    "\"block_type\":\"text|paragraph|title|table|cell|form_field|key_value|checkbox|selection_mark\","
    "\"table_id\":null,\"row\":null,\"col\":null}]}. "
    "If page or bbox cannot be determined, use page=1 and an empty bbox. Do not invent content."
)


def document_kind_for_section(section: str, profile: DocumentProfile | None = None) -> str:
    if profile is None:
        return "document"
    for rule in profile.document_kind_rules:
        if section in rule.sections:
            return rule.kind
    return profile.default_document_kind or "document"


def extraction_system_prompt(profile: DocumentProfile | None = None) -> str:
    if profile and profile.extraction_system_prompt:
        return profile.extraction_system_prompt
    return DEFAULT_EXTRACTION_SYSTEM_PROMPT


def extraction_rules(profile: DocumentProfile | None = None) -> list[str]:
    if profile and profile.extraction_rules:
        return profile.extraction_rules
    return DEFAULT_EXTRACTION_RULES


def document_ai_prompt(profile: DocumentProfile | None = None) -> str:
    if profile and profile.document_ai_prompt:
        return profile.document_ai_prompt
    return DEFAULT_DOCUMENT_AI_PROMPT
