from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LlmPolicy(BaseModel):
    enabled: bool = False
    trigger_statuses: list[str] = Field(default_factory=lambda: ["missing", "low_confidence", "conflict"])
    evidence_budget: int = Field(default=800, ge=80)
    allow_image_crop: bool = False
    prompt_profile: str = "default"
    skip_when_no_evidence: bool = True
    max_evidence_items_for_llm: int = Field(default=2, ge=1, le=5)


class FieldDefinition(BaseModel):
    key: str
    label: str
    export_header: str
    allowed_codes: list[str]
    type: str = "enum"
    extract_mode: str = "rule_first"
    source_sections: list[str] = Field(default_factory=list)
    excluded_sections: list[str] = Field(default_factory=list)
    synonyms: list[str] = Field(default_factory=list)
    negation_terms: list[str] = Field(default_factory=list)
    evidence_priority: list[str] = Field(default_factory=list)
    rule_strategy: dict[str, Any] = Field(default_factory=dict)
    review_policy: str = "required_if_missing"
    max_evidence_items: int = Field(default=5, ge=1)
    evidence_window_chars: int = Field(default=320, ge=80)
    llm: LlmPolicy = Field(default_factory=LlmPolicy)
    requires_review_on_conflict: bool = True
    phase: int = 1


class FieldDictionary(BaseModel):
    version: str
    fields: list[FieldDefinition]

    def by_key(self, key: str) -> FieldDefinition:
        for field in self.fields:
            if field.key == key:
                return field
        raise KeyError(f"Unknown field key: {key}")

    @property
    def export_headers(self) -> list[str]:
        return [field.export_header for field in self.fields]
