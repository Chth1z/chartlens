from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


DICTIONARY_PATH = Path(__file__).resolve().parents[1] / "data" / "field_dictionary.yaml"


class LlmPolicy(BaseModel):
    enabled: bool = False
    trigger_statuses: list[str] = Field(default_factory=lambda: ["missing", "low_confidence", "conflict"])
    evidence_budget: int = Field(default=800, ge=80)
    allow_image_crop: bool = False
    prompt_profile: str = "default"


class FieldDefinition(BaseModel):
    key: str
    label: str
    export_header: str
    allowed_codes: list[str]
    type: str = "enum"
    extract_mode: str = "rule_first"
    source_sections: list[str] = Field(default_factory=list)
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


@lru_cache(maxsize=1)
def load_field_dictionary(path: str | Path | None = None) -> FieldDictionary:
    dictionary_path = Path(path) if path else DICTIONARY_PATH
    with dictionary_path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    return FieldDictionary.model_validate(payload)
