"""Health, config introspection, and auth-status routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.contracts import (
    AuthStatusResponse,
    ConfigArtifactResponse,
    ConfigCatalogResponse,
    ConfigResponse,
    FieldDictionaryResponse,
    HealthResponse,
    MaintenanceResponse,
)
from app.core.config_loader import (
    list_document_profile_ids,
    list_evaluation_profiles,
    list_export_template_ids,
    list_extraction_schema_ids,
    list_model_profiles,
    list_ocr_profiles,
    load_export_template,
    load_extraction_schema,
    read_config_artifact,
    validate_project_config,
)
from app.core.settings import settings

from ._helpers import (
    _active_api_key_configured,
    _active_provider_label,
    _config_rule_ids,
    _online_model_available,
)


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> dict:
    return {"ok": True, "app": settings.app_name, "config_errors": validate_project_config()}


@router.get("/config", response_model=ConfigResponse)
def config() -> dict:
    schema = load_extraction_schema()
    template = load_export_template()
    return {
        "schema": schema.model_dump(),
        "export_template": template.model_dump(),
        "config_errors": validate_project_config(),
    }


@router.get("/config/catalog", response_model=ConfigCatalogResponse)
def config_catalog() -> dict:
    return {
        "config_root": str(settings.config_dir),
        "active": {
            "document_profile": settings.document_profile,
            "extraction_schema": settings.extraction_schema,
            "export_template": settings.export_template,
            "model_profile": settings.model_profile,
            "ocr_profile": settings.ocr_profile,
        },
        "document_profiles": list_document_profile_ids(),
        "extraction_schemas": list_extraction_schema_ids(),
        "export_templates": list_export_template_ids(),
        "model_profiles": [profile.profile_id for profile in list_model_profiles()],
        "ocr_profiles": [profile.profile_id for profile in list_ocr_profiles()],
        "evaluation_profiles": [profile.profile_id for profile in list_evaluation_profiles()],
        "validation_rules": _config_rule_ids(),
    }


@router.get("/config/{kind}/{config_id}", response_model=ConfigArtifactResponse)
def config_artifact(kind: str, config_id: str) -> dict:
    try:
        return read_config_artifact(kind, config_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config artifact not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/auth/me", response_model=AuthStatusResponse)
def auth_status() -> dict:
    return {
        "enabled": False,
        "auth_provider": "chatgpt",
        "configured": True,
        "missing_config": [],
        "config_warnings": [],
        "chatgpt_login_available": False,
        "authenticated": True,
        "user": {"sub": "local", "email": None, "name": "Local user"},
        "session_auth": {
            "enabled": False,
            "authenticated": True,
            "provider": "local",
            "user": {"sub": "local", "email": None, "name": "Local user"},
            "issued_at": None,
            "expires_at": None,
            "cookie_name": "eyex_session",
        },
        "model_auth": {
            "auth_mode": settings.llm_mode,
            "provider": _active_provider_label(),
            "online_model_available": _online_model_available(),
            "api_key_configured": _active_api_key_configured(),
            "chatgpt_codex_configured": False,
            "token_cache_exists": False,
            "token_cache_path": "",
            "updated_at": None,
            "expires_at": None,
            "user": None,
        },
    }


@router.delete("/auth/model-token", response_model=MaintenanceResponse)
def delete_model_token() -> dict:
    return {"ok": True, "affected_count": 0, "message": "当前版本未保存 ChatGPT/Codex token。"}


@router.get("/field-dictionary", response_model=FieldDictionaryResponse)
def field_dictionary() -> dict:
    schema = load_extraction_schema()
    return {"version": schema.version, "fields": [field.model_dump() for field in schema.fields]}
