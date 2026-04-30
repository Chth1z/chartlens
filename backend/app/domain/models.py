from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DocumentIRBlock(BaseModel):
    block_id: str
    page: int = Field(ge=1)
    reading_order: int = Field(ge=1)
    text: str
    bbox: list[float] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    block_type: Literal[
        "line",
        "paragraph",
        "table",
        "title",
        "text",
        "form_field",
        "cell",
        "checkbox",
        "selection_mark",
        "key_value",
    ] = "paragraph"
    section_id: str = "unknown"
    section_label: str = "未知"
    document_kind: str = "unknown"
    table_id: str | None = None
    row: int | None = None
    col: int | None = None
    source_engine: str | None = None
    source_page_kind: str = "unknown"
    ocr_profile: str | None = None
    layout_profile: str | None = None
    quality_flags: list[str] = Field(default_factory=list)
    model_name: str | None = None
    model_version: str | None = None
    accelerator: str | None = None
    engine_version: str | None = None
    route_profile_id: str | None = None


class OcrRouteRule(BaseModel):
    page_kinds: list[str] = Field(default_factory=list)
    engines: list[str] = Field(default_factory=list)
    description: str | None = None


class OcrEngineConfig(BaseModel):
    engine_id: str
    label: str | None = None
    enabled: bool = True
    model_name: str | None = None
    model_version: str | None = None
    accelerator: str = "auto"
    priority: int = 100
    remote_url: str | None = None
    experimental: bool = False
    options: dict[str, Any] = Field(default_factory=dict)


class OcrProfile(BaseModel):
    profile_id: str
    label: str
    version: str = "1.0.0"
    page_router: list[OcrRouteRule] = Field(default_factory=list)
    engines: list[OcrEngineConfig] = Field(default_factory=list)
    cache_policy: dict[str, Any] = Field(default_factory=dict)
    gpu_policy: dict[str, Any] = Field(default_factory=dict)
    quality_thresholds: dict[str, Any] = Field(default_factory=dict)

    def engine_config(self, engine_id: str) -> OcrEngineConfig | None:
        return next((engine for engine in self.engines if engine.engine_id == engine_id), None)


class OcrDeviceStatus(BaseModel):
    requested: str = "auto"
    resolved: str = "cpu"
    accelerator: str = "cpu"
    compiled_cuda: bool = False
    compiled_rocm: bool = False
    current: str = "cpu"
    available_accelerators: list[str] = Field(default_factory=list)
    probes: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class DocumentIRSection(BaseModel):
    section_id: str
    label: str
    aliases: list[str] = Field(default_factory=list)
    page_range: list[int] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class DocumentIR(BaseModel):
    document_id: str
    profile_id: str
    source_filename: str
    blocks: list[DocumentIRBlock] = Field(default_factory=list)
    sections: list[DocumentIRSection] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FieldGroup(BaseModel):
    key: str
    label: str
    source_sections: list[str] = Field(default_factory=list)
    prompt_profile: str = "default"
    semantic_strategy: Literal["rule_shortcut", "llm_semantic", "llm_facts_then_compute"] = "llm_semantic"
    max_context_chars: int = 3200
    model_profile: str | None = None


class LlmFieldConfig(BaseModel):
    enabled: bool = True
    evidence_budget: int = 800
    max_evidence_items: int = 6
    prompt_profile: str = "default"
    skip_when_no_evidence: bool = False


class RulePattern(BaseModel):
    pattern: str
    normalized_code: str | None = None
    code_map: dict[str, str] = Field(default_factory=dict)
    raw_group: int | str = 1
    evidence_group: int | str = 0
    confidence: float = Field(default=0.92, ge=0.0, le=1.0)
    summary: str | None = None


class FieldDefinition(BaseModel):
    key: str
    field_group_key: str
    label: str
    export_header: str
    type: Literal["enum", "number", "string", "duration", "fact_array"] = "enum"
    allowed_codes: list[str] = Field(default_factory=lambda: ["unknown"])
    extract_mode: Literal["rule_first", "llm_semantic", "fact_then_code", "computed_from_facts", "manual"] = "llm_semantic"
    source_sections: list[str] = Field(default_factory=list)
    excluded_sections: list[str] = Field(default_factory=list)
    synonyms: list[str] = Field(default_factory=list)
    negation_terms: list[str] = Field(default_factory=list)
    evidence_priority: list[str] = Field(default_factory=list)
    code_map: dict[str, list[str]] = Field(default_factory=dict)
    review_policy: str = "required_if_missing"
    phase: int = 1
    unknown_allowed: bool = True
    llm: LlmFieldConfig = Field(default_factory=LlmFieldConfig)
    rule_patterns: list[RulePattern] = Field(default_factory=list)


class ExtractionSchema(BaseModel):
    schema_id: str
    version: str
    label: str
    field_groups: list[FieldGroup]
    fields: list[FieldDefinition]

    def group_by_key(self, key: str) -> FieldGroup:
        for group in self.field_groups:
            if group.key == key:
                return group
        raise KeyError(key)

    def fields_for_group(self, key: str) -> list[FieldDefinition]:
        return [field for field in self.fields if field.field_group_key == key and field.phase == 1]

    def field_by_key(self, key: str) -> FieldDefinition:
        for field in self.fields:
            if field.key == key:
                return field
        raise KeyError(key)


class ExportColumn(BaseModel):
    field_key: str
    header: str
    unknown_value: str | None = None


class ExportTemplate(BaseModel):
    template_id: str
    version: str = "1.0.0"
    label: str
    empty_value: str = ""
    unknown_value: str = ""
    columns: list[ExportColumn]


class DocumentKindRule(BaseModel):
    kind: str
    sections: list[str] = Field(default_factory=list)


class RedactionPattern(BaseModel):
    key: str
    pattern: str
    replacement: str = "[REDACTED]"
    blocks_online_llm: bool = False


class DocumentProfile(BaseModel):
    profile_id: str
    label: str
    section_aliases: dict[str, list[str]]
    excluded_phi_labels: list[str] = Field(default_factory=list)
    default_document_kind: str = "document"
    document_kind_rules: list[DocumentKindRule] = Field(default_factory=list)
    phi_inline_labels: list[str] = Field(default_factory=list)
    phi_patterns: list[RedactionPattern] = Field(default_factory=list)
    extraction_system_prompt: str | None = None
    extraction_rules: list[str] = Field(default_factory=list)
    document_ai_prompt: str | None = None


class ModelProfile(BaseModel):
    profile_id: str
    provider: Literal["openai_responses", "openai_compatible", "anthropic_messages", "google_gemini", "disabled"] = "openai_responses"
    model: str
    label: str | None = None
    provider_id: str | None = None
    model_ref: str | None = None
    api: Literal["openai-responses", "openai-completions", "anthropic-messages", "google-gemini", "disabled"] | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    api_key_value: str | None = Field(default=None, exclude=True)
    auth_env_vars: list[str] = Field(default_factory=list)
    auth_optional: bool = False
    response_format: Literal["json_schema", "json_object"] = "json_schema"
    reasoning_effort: str = "low"
    prompt_cache_key: str = "eyex-clinical-extraction-v1"
    max_output_tokens: int = 4096
    store: bool = False
    temperature: float = 0.0
    fallbacks: list[str] = Field(default_factory=list)
    input: list[str] = Field(default_factory=lambda: ["text"])
    context_window: int | None = None
    context_tokens: int | None = None
    cost: dict[str, float] = Field(default_factory=dict)
    compat: dict[str, Any] = Field(default_factory=dict)


class EvidenceCandidate(BaseModel):
    block_id: str
    text: str
    page: int = 1
    bbox: list[float] = Field(default_factory=list)
    section_label: str = "未知"
    document_kind: str = "unknown"
    ocr_confidence: float = 0.0
    score: float = 0.0
    match_terms: list[str] = Field(default_factory=list)
    score_reason: str | None = None
    pack_hash: str | None = None
    context_text: str | None = None
    token_estimate: int = 0
    negated: bool = False
    uncertain: bool = False
    family_context: bool = False
    rank: int = 0


class EvidencePack(BaseModel):
    field_key: str
    pack_hash: str
    rank: int
    block_id: str
    text: str
    context_text: str
    page: int = 1
    bbox: list[float] = Field(default_factory=list)
    section_label: str = "未知"
    document_kind: str = "unknown"
    ocr_confidence: float = 0.0
    score: float = 0.0
    match_terms: list[str] = Field(default_factory=list)
    score_reason: str | None = None
    negated: bool = False
    uncertain: bool = False
    family_context: bool = False
    token_estimate: int = 0
    neighbor_block_ids: list[str] = Field(default_factory=list)


class ExtractedFact(BaseModel):
    fact_type: str
    raw_text: str
    normalized: str | None = None
    evidence_span: str | None = None
    evidence_block_id: str | None = None
    confidence: float = 0.0


class ExtractionCandidate(BaseModel):
    field_key: str
    field_group_key: str | None = None
    raw_value: str | None = None
    normalized_code: str | None = "unknown"
    status: Literal["confirmed", "unknown", "not_mentioned", "conflict", "derived_candidate", "error"] = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_text: str | None = None
    evidence_span: str | None = None
    evidence_block_id: str | None = None
    evidence_type: Literal[
        "explicit_positive",
        "explicit_negative",
        "explicit_composite_negative",
        "explicit_recorded_score",
        "derived",
        "inferred",
        "no_evidence",
        "conflict",
        "event_fact",
    ] | None = "no_evidence"
    page: int | None = None
    bbox: list[float] = Field(default_factory=list)
    facts: list[ExtractedFact] = Field(default_factory=list)
    reasoning_summary: str | None = None
    review_required: bool = True
    error_code: str | None = None
    validator_messages: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    acceptance_reason: str | None = None
    risk_level: Literal["low", "medium", "high", "critical"] = "medium"
    evidence_candidates: list[EvidenceCandidate] = Field(default_factory=list)
    evidence_packs: list[EvidencePack] = Field(default_factory=list)
    model_profile_id: str | None = None
    ocr_engine: str | None = None
    validation_state: Literal["unknown", "accepted", "needs_review", "rejected", "reviewed"] = "needs_review"

    @field_validator("bbox", mode="before")
    @classmethod
    def _coerce_bbox(cls, value):
        return [] if value is None else value

    @field_validator("status", mode="before")
    @classmethod
    def _coerce_status(cls, value):
        return "not_mentioned" if value == "no_evidence" else value


class ValidatedFieldResult(ExtractionCandidate):
    auto_accepted: bool = False


class ReviewDecision(BaseModel):
    field_key: str
    normalized_code: str
    raw_value: str | None = None
    reviewer: str = "local_user"
    comment: str | None = None
    evidence_span: str | None = None
    evidence_block_id: str | None = None
    decided_at: datetime = Field(default_factory=utc_now)


class CaseSummary(BaseModel):
    case_id: str
    filename: str
    status: str
    created_at: datetime
    updated_at: datetime
    result_count: int = 0
    review_required_count: int = 0


class EvaluationRequest(BaseModel):
    case_id: str
    gold: dict[str, str]


class EvaluationGoldCase(BaseModel):
    case_id: str
    gold: dict[str, str]
    tags: list[str] = Field(default_factory=list)


class EvaluationProfile(BaseModel):
    profile_id: str
    label: str
    schema_id: str
    gold_cases: list[EvaluationGoldCase] = Field(default_factory=list)
    field_tags: dict[str, list[str]] = Field(default_factory=dict)
    thresholds: dict[str, float] = Field(default_factory=dict)
    token_budget: dict[str, int] = Field(default_factory=dict)


class EvaluationResult(BaseModel):
    case_id: str
    total: int
    correct: int
    accuracy: float
    unknown_count: int
    missing_evidence_failures: list[str] = Field(default_factory=list)
