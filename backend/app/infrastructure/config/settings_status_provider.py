from __future__ import annotations

from typing import Any

import yaml
from pydantic import ValidationError

from app.application.settings_status import SettingsValidationRequest
from app.core.config import settings
from app.domain.field_definitions import FieldDictionary
from app.domain.system_config import SystemConfig
from app.infrastructure.config.field_dictionary import DICTIONARY_PATH, load_field_dictionary
from app.infrastructure.config.system_config import SYSTEM_CONFIG_PATH, load_system_config


class YamlSettingsStatusProvider:
    def system_settings_payload(self) -> dict[str, Any]:
        config = load_system_config()
        return {
            "system_config": {
                "path": str(SYSTEM_CONFIG_PATH),
                "version": config.version,
                "ocr_default_profile": config.ocr.default_profile,
                "layout_default_profile": config.layout.default_profile,
                "llm_default_profile": config.llm.default_profile,
                "ocr_profiles": list(config.ocr.profiles),
                "layout_profiles": list(config.layout.profiles),
                "llm_profiles": list(config.llm.profiles),
                "vision_fallback_enabled": config.llm.vision_fallback.enabled,
            }
        }

    def field_dictionary_payload(self) -> dict[str, Any]:
        dictionary = load_field_dictionary()
        return {
            "field_dictionary": {
                "path": str(DICTIONARY_PATH),
                "version": dictionary.version,
                "field_count": len(dictionary.fields),
                "phase_1_count": sum(1 for field in dictionary.fields if field.phase == 1),
                "fields": [field.model_dump() for field in dictionary.fields],
            }
        }

    def runtime_settings_payload(self) -> dict[str, Any]:
        return {
            "runtime_settings": {
                "database_url": settings.database_url,
                "storage_dir": str(settings.storage_dir),
                "sync_pipeline": settings.sync_pipeline,
                "case_workers": settings.case_workers,
                "ocr_page_workers": settings.ocr_page_workers,
                "llm_workers": settings.llm_workers,
                "ocr_profile": settings.ocr_profile,
                "layout_profile": settings.layout_profile,
                "model_mode": settings.model_mode,
                "openai_auth_mode": settings.openai_auth_mode,
                "oauth_enabled": settings.oauth_enabled,
                "oauth_provider": settings.oauth_provider,
                "chatgpt_token_cache_path": str(settings.chatgpt_token_cache_path),
            },
            "restart_required_hints": _restart_required_hints(),
        }

    def validate_settings_payload(self, request: object) -> dict[str, Any]:
        if not isinstance(request, SettingsValidationRequest):
            request = SettingsValidationRequest.model_validate(request)
        errors: list[str] = []
        system_config = _load_system_config_from_yaml(request.system_config_yaml, errors)
        field_dictionary = _load_field_dictionary_from_yaml(request.field_dictionary_yaml, errors)
        if system_config is not None:
            _validate_active_profiles(system_config, errors)
        if field_dictionary is not None:
            _validate_field_dictionary(field_dictionary, errors)
        return {
            "ok": not errors,
            "validation_errors": errors,
            "restart_required_hints": _restart_required_hints(),
        }


def _load_system_config_from_yaml(yaml_text: str | None, errors: list[str]) -> SystemConfig | None:
    try:
        if yaml_text is None:
            return load_system_config()
        payload = yaml.safe_load(yaml_text)
        return SystemConfig.model_validate(payload)
    except (OSError, yaml.YAMLError, ValidationError, ValueError) as exc:
        errors.append(f"Invalid system config: {_summarize(exc)}")
        return None


def _load_field_dictionary_from_yaml(yaml_text: str | None, errors: list[str]) -> FieldDictionary | None:
    try:
        if yaml_text is None:
            return load_field_dictionary()
        payload = yaml.safe_load(yaml_text)
        return FieldDictionary.model_validate(payload)
    except (OSError, yaml.YAMLError, ValidationError, ValueError) as exc:
        errors.append(f"Invalid field dictionary: {_summarize(exc)}")
        return None


def _validate_active_profiles(config: SystemConfig, errors: list[str]) -> None:
    if settings.ocr_profile not in config.ocr.profiles:
        errors.append(f"CHARTLENS_OCR_PROFILE '{settings.ocr_profile}' is not defined in system_config.yaml")
    if settings.layout_profile not in config.layout.profiles:
        errors.append(f"CHARTLENS_LAYOUT_PROFILE '{settings.layout_profile}' is not defined in system_config.yaml")
    if settings.model_mode not in config.llm.profiles:
        errors.append(f"CHARTLENS_MODEL_MODE '{settings.model_mode}' is not defined in system_config.yaml")


def _validate_field_dictionary(dictionary: FieldDictionary, errors: list[str]) -> None:
    seen: set[str] = set()
    for field in dictionary.fields:
        if field.key in seen:
            errors.append(f"Duplicate field key: {field.key}")
        seen.add(field.key)


def _restart_required_hints() -> list[str]:
    return [
        "CHARTLENS_OCR_PROFILE",
        "CHARTLENS_LAYOUT_PROFILE",
        "CHARTLENS_MODEL_MODE",
        "CHARTLENS_SYNC_PIPELINE",
        "CHARTLENS_CASE_WORKERS",
        "CHARTLENS_OCR_PAGE_WORKERS",
        "CHARTLENS_OPENAI_AUTH_MODE",
    ]


def _summarize(exc: Exception) -> str:
    message = str(exc).replace("\n", " ").strip()
    return message[:240] if message else exc.__class__.__name__
