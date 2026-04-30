from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel

from app.core.settings import settings
from app.domain.models import (
    DocumentProfile,
    EvaluationProfile,
    ExportTemplate,
    ExtractionSchema,
    ModelProfile,
    OcrProfile,
)

T = TypeVar("T", bound=BaseModel)


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Config file must contain a mapping: {path}")
    return loaded


def _load_model(path: Path, model_type: type[T]) -> T:
    return model_type.model_validate(_load_yaml(path))


@lru_cache(maxsize=16)
def load_document_profile(profile_id: str | None = None) -> DocumentProfile:
    target = profile_id or settings.document_profile
    return _load_model(settings.config_dir / "document_profiles" / f"{target}.yaml", DocumentProfile)


@lru_cache(maxsize=16)
def load_extraction_schema(schema_id: str | None = None) -> ExtractionSchema:
    target = schema_id or settings.extraction_schema
    return _load_model(settings.config_dir / "extraction_schemas" / f"{target}.yaml", ExtractionSchema)


@lru_cache(maxsize=16)
def load_export_template(template_id: str | None = None) -> ExportTemplate:
    target = template_id or settings.export_template
    return _load_model(settings.config_dir / "export_templates" / f"{target}.yaml", ExportTemplate)


@lru_cache(maxsize=16)
def load_model_profile(profile_id: str | None = None) -> ModelProfile:
    target = profile_id or settings.model_profile
    return _load_model(settings.config_dir / "model_profiles" / f"{target}.yaml", ModelProfile)


@lru_cache(maxsize=16)
def load_ocr_profile(profile_id: str | None = None) -> OcrProfile:
    target = profile_id or settings.ocr_profile
    return _load_model(settings.config_dir / "ocr_profiles" / f"{target}.yaml", OcrProfile)


def list_ocr_profiles() -> list[OcrProfile]:
    profile_dir = settings.config_dir / "ocr_profiles"
    if not profile_dir.exists():
        return []
    return [_load_model(path, OcrProfile) for path in sorted(profile_dir.glob("*.yaml"))]


def load_evaluation_profile(profile_id: str) -> EvaluationProfile:
    return _load_model(settings.config_dir / "evaluation_profiles" / f"{profile_id}.yaml", EvaluationProfile)


def list_evaluation_profiles() -> list[EvaluationProfile]:
    profile_dir = settings.config_dir / "evaluation_profiles"
    if not profile_dir.exists():
        return []
    return [_load_model(path, EvaluationProfile) for path in sorted(profile_dir.glob("*.yaml"))]


def list_model_profiles() -> list[ModelProfile]:
    profiles: list[ModelProfile] = []
    for path in sorted((settings.config_dir / "model_profiles").glob("*.yaml")):
        profiles.append(_load_model(path, ModelProfile))
    return profiles


def validate_project_config() -> list[str]:
    messages: list[str] = []
    schema = load_extraction_schema()
    template = load_export_template()
    group_keys = {group.key for group in schema.field_groups}
    field_keys = {field.key for field in schema.fields}

    for field in schema.fields:
        if field.field_group_key not in group_keys:
            messages.append(f"Field {field.key} references missing group {field.field_group_key}")
        if field.extract_mode != "manual" and field.unknown_allowed and "unknown" not in field.allowed_codes:
            messages.append(f"Field {field.key} allows unknown but allowed_codes does not include unknown")
        if field.extract_mode in {"llm_semantic", "fact_then_code", "computed_from_facts"} and "unknown" not in field.allowed_codes:
            messages.append(f"Complex field {field.key} must allow unknown")

    for column in template.columns:
        if column.field_key not in field_keys:
            messages.append(f"Export column references missing field {column.field_key}")

    return messages
