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
    OcrEvaluationProfile,
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


def validate_ocr_evaluation_profiles() -> list[str]:
    messages: list[str] = []
    ocr_eval_dir = settings.config_dir / "ocr_evaluation_profiles"
    if not ocr_eval_dir.exists():
        return messages
    for path in sorted(ocr_eval_dir.glob("*.yaml")):
        profile = _load_model(path, OcrEvaluationProfile)
        is_template_profile = bool(profile.thresholds.get("template"))
        requires_hardware_contract = bool(
            profile.thresholds.get("requires_real_hardware")
            or profile.thresholds.get("requires_deidentified_corpus")
        )
        for case in profile.cases:
            document_path = Path(case.document_path)
            resolved = document_path if document_path.is_absolute() else (path.parent / document_path).resolve()
            if not is_template_profile and not resolved.exists():
                messages.append(
                    f"OCR evaluation case {case.case_id} in {path.name} references missing document {case.document_path}"
                )
            if not case.truth_pages:
                messages.append(f"OCR evaluation case {case.case_id} in {path.name} must define truth_pages")
            if requires_hardware_contract:
                if not _has_complete_truth_blocks(case.truth_blocks):
                    messages.append(
                        f"OCR evaluation case {case.case_id} in {path.name} must define truth_blocks with text, bbox, reading_order, and page"
                    )
                if not _has_complete_truth_tables(case.truth_tables):
                    messages.append(
                        f"OCR evaluation case {case.case_id} in {path.name} must define truth_tables for table/layout evaluation"
                    )
    return messages


@lru_cache(maxsize=16)
def load_document_profile(profile_id: str | None = None) -> DocumentProfile:
    target = profile_id or settings.document_profile
    return _load_model(settings.config_dir / "document_profiles" / f"{target}.yaml", DocumentProfile)


def list_document_profile_ids() -> list[str]:
    return _list_config_ids("document_profiles")


@lru_cache(maxsize=16)
def load_extraction_schema(schema_id: str | None = None) -> ExtractionSchema:
    target = schema_id or settings.extraction_schema
    return _load_model(settings.config_dir / "extraction_schemas" / f"{target}.yaml", ExtractionSchema)


def list_extraction_schema_ids() -> list[str]:
    return _list_config_ids("extraction_schemas")


@lru_cache(maxsize=16)
def load_export_template(template_id: str | None = None) -> ExportTemplate:
    target = template_id or settings.export_template
    return _load_model(settings.config_dir / "export_templates" / f"{target}.yaml", ExportTemplate)


def list_export_template_ids() -> list[str]:
    return _list_config_ids("export_templates")


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


@lru_cache(maxsize=16)
def load_ocr_evaluation_profile(profile_id: str) -> OcrEvaluationProfile:
    return _load_model(settings.config_dir / "ocr_evaluation_profiles" / f"{profile_id}.yaml", OcrEvaluationProfile)


def list_ocr_evaluation_profiles() -> list[OcrEvaluationProfile]:
    profile_dir = settings.config_dir / "ocr_evaluation_profiles"
    if not profile_dir.exists():
        return []
    return [_load_model(path, OcrEvaluationProfile) for path in sorted(profile_dir.glob("*.yaml"))]


def list_model_profiles() -> list[ModelProfile]:
    profiles: list[ModelProfile] = []
    for path in sorted((settings.config_dir / "model_profiles").glob("*.yaml")):
        profiles.append(_load_model(path, ModelProfile))
    return profiles


def read_config_artifact(kind: str, config_id: str) -> dict:
    allowed = {
        "document_profiles",
        "extraction_schemas",
        "export_templates",
        "model_profiles",
        "ocr_profiles",
        "ocr_evaluation_profiles",
        "evaluation_profiles",
        "validation_rules",
    }
    if kind not in allowed:
        raise ValueError(f"Unsupported config kind: {kind}")
    if not config_id or any(part in config_id for part in ("..", "/", "\\")):
        raise ValueError("Invalid config id")
    path = settings.config_dir / kind / f"{config_id}.yaml"
    parsed = _load_yaml(path)
    return {
        "kind": kind,
        "config_id": config_id,
        "path": str(path),
        "yaml": path.read_text(encoding="utf-8"),
        "parsed": parsed,
    }


def _list_config_ids(kind: str) -> list[str]:
    profile_dir = settings.config_dir / kind
    if not profile_dir.exists():
        return []
    return [path.stem for path in sorted(profile_dir.glob("*.yaml"))]


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
        for rule in field.pre_redaction_derivations:
            if rule.normalized_code not in field.allowed_codes:
                messages.append(f"Pre-redaction derivation for {field.key} emits disallowed code {rule.normalized_code}")
            if rule.safe_evidence_span not in rule.safe_text:
                messages.append(f"Pre-redaction derivation for {field.key} must keep safe evidence span in safe text")
        if field.evidence_policy.require_visual_confirmation and "image" not in field.evidence_policy.allowed_evidence_sources:
            messages.append(f"Field {field.key} requires visual confirmation but image evidence is not allowed")
        if field.evidence_policy.implicit_negative_policy != "none" and not {"1", "0"}.issubset(set(field.allowed_codes)):
            messages.append(f"Field {field.key} uses implicit negative policy but is not a binary coded field")

    for column in template.columns:
        if column.field_key not in field_keys:
            messages.append(f"Export column references missing field {column.field_key}")

    messages.extend(validate_ocr_evaluation_profiles())

    return messages


def _has_complete_truth_blocks(blocks: list[dict]) -> bool:
    if not blocks:
        return False
    required = {"text", "bbox", "reading_order", "page"}
    for block in blocks:
        if not required.issubset(block):
            return False
        if not str(block.get("text") or "").strip():
            return False
        bbox = block.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            return False
        if not all(isinstance(value, int | float) for value in bbox):
            return False
        if not isinstance(block.get("reading_order"), int) or block["reading_order"] < 1:
            return False
        if not isinstance(block.get("page"), int) or block["page"] < 1:
            return False
    return True


def _has_complete_truth_tables(tables: list[dict]) -> bool:
    if not tables:
        return False
    for table in tables:
        cells = table.get("cells")
        if not isinstance(cells, list) or not cells:
            return False
        for cell in cells:
            if not {"text", "bbox", "row", "col"}.issubset(cell):
                return False
            if not str(cell.get("text") or "").strip():
                return False
            bbox = cell.get("bbox")
            if not isinstance(bbox, list) or len(bbox) != 4:
                return False
            if not all(isinstance(value, int | float) for value in bbox):
                return False
            if not isinstance(cell.get("row"), int) or cell["row"] < 1:
                return False
            if not isinstance(cell.get("col"), int) or cell["col"] < 1:
                return False
    return True


def invalidate_config_cache() -> int:
    """Clear all config lru_cache entries. Returns number of caches cleared.

    Call this after modifying YAML files in config/ to pick up changes
    without restarting the server.
    """
    caches = [
        load_document_profile,
        load_extraction_schema,
        load_export_template,
        load_model_profile,
        load_ocr_profile,
        load_ocr_evaluation_profile,
    ]
    for cache_fn in caches:
        cache_fn.cache_clear()
    return len(caches)
