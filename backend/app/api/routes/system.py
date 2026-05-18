"""System settings, runtime settings, and maintenance routes."""

from __future__ import annotations

import os
import shutil
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.contracts import (
    FieldDictionarySettingsResponse,
    MaintenanceResponse,
    ProjectConfigResponse,
    RuntimeSettingsResponse,
    SettingsValidationResponse,
    SystemSettingsResponse,
)
from app.core.config_loader import (
    list_document_profile_ids,
    list_ocr_profiles,
    load_document_profile,
    load_export_template,
    load_extraction_schema,
    validate_project_config,
)
from app.core.database import (
    CaseRecord,
    FieldResultRecord,
    ModelCallRecord,
    ProcessingEventRecord,
    ProcessingRunRecord,
    ReviewAuditRecord,
    VisionFallbackRequestRecord,
    get_db,
)
from app.core.settings import settings
from app.services.diagnostics import frontend_evidence_config
from app.services.model_selection import model_profiles_payload
from app.services.ocr_accelerators import resolve_ocr_device_status
from app.services.runtime_status import build_runtime_services

from ._helpers import _active_ocr_profile_payload, _runtime_ocr_engine_names


router = APIRouter()


@router.get("/project-config", response_model=ProjectConfigResponse)
def project_config() -> dict:
    schema = load_extraction_schema()
    template = load_export_template()
    document_profile = load_document_profile()
    return {
        "app_profile": {
            "profile_id": "eyex",
            "version": "1.0.0",
            "label": "EYEX",
            "terms": {
                "document": "病例",
                "document_queue": "病例队列",
                "upload": "上传病例 PDF / 图片 / 文本",
                "field_results": "字段结果",
            },
            "default_document_profile_id": document_profile.profile_id,
            "default_extraction_schema_id": schema.schema_id,
            "default_export_template_id": template.template_id,
            "ocr_engine_policy": "intelligent_only",
        },
        "document_profile": {
            "profile_id": document_profile.profile_id,
            "version": "1.0.0",
            "label": document_profile.label,
            "section_aliases": document_profile.section_aliases,
            "frontend": frontend_evidence_config(),
        },
        "extraction_schema": schema.model_dump(),
        "export_template": {
            **template.model_dump(),
            "columns": [
                {
                    "field_key": column.field_key,
                    "header": column.header,
                    "empty_value": template.empty_value,
                    "unknown_value": column.unknown_value if column.unknown_value is not None else template.unknown_value,
                }
                for column in template.columns
            ],
        },
    }


@router.get("/settings/system", response_model=SystemSettingsResponse)
def system_settings() -> dict:
    profiles = model_profiles_payload()["profiles"]
    ocr_profile = _active_ocr_profile_payload()
    device = resolve_ocr_device_status()
    return {
        "system_config": {
            "path": str(settings.config_dir),
            "version": "1.0.0",
            "ocr_default_profile": settings.ocr_profile,
            "ocr_active_profile": ocr_profile,
            "ocr_accelerator": device.resolved,
            "available_accelerators": device.probes,
            "ocr_strategy": settings.ocr_strategy,
            "ocr_profile_engines": _runtime_ocr_engine_names(ocr_profile),
            "ocr_document_ai_configured": bool(settings.ocr_document_ai_url),
            "ocr_openai_model": settings.ocr_openai_model or settings.openai_model,
            "ocr_openai_configured": bool(settings.openai_api_key or os.environ.get("OPENAI_API_KEY")),
            "layout_default_profile": settings.document_profile,
            "llm_default_profile": model_profiles_payload()["active_profile_id"],
            "ocr_profiles": [profile.profile_id for profile in list_ocr_profiles()],
            "layout_profiles": list_document_profile_ids(),
            "llm_profiles": [profile["profile_id"] for profile in profiles],
            "vision_fallback_enabled": True,
        }
    }


@router.get("/settings/field-dictionary", response_model=FieldDictionarySettingsResponse)
def field_dictionary_settings() -> dict:
    schema = load_extraction_schema()
    return {
        "field_dictionary": {
            "path": str(settings.config_dir / "extraction_schemas" / f"{schema.schema_id}.yaml"),
            "version": schema.version,
            "field_count": len(schema.fields),
            "phase_1_count": len([field for field in schema.fields if field.phase == 1]),
            "fields": [field.model_dump() for field in schema.fields],
        }
    }


@router.get("/settings/runtime", response_model=RuntimeSettingsResponse)
def runtime_settings() -> dict:
    active = model_profiles_payload()["active_profile_id"]
    ocr_profile = _active_ocr_profile_payload()
    device = resolve_ocr_device_status()
    services = build_runtime_services()
    return {
        "runtime_settings": {
            "database_url": settings.database_url,
            "storage_dir": str(settings.storage_dir),
            "sync_pipeline": not settings.auto_process_uploads,
            "case_workers": settings.case_workers,
            "ocr_page_workers": 1,
            "llm_workers": settings.llm_workers,
            "ocr_profile": settings.ocr_profile,
            "ocr_active_profile": ocr_profile,
            "ocr_accelerator": device.resolved,
            "available_accelerators": device.probes,
            "ocr_strategy": settings.ocr_strategy,
            "ocr_profile_engines": _runtime_ocr_engine_names(ocr_profile),
            "ocr_document_ai_configured": bool(settings.ocr_document_ai_url),
            "ocr_openai_model": settings.ocr_openai_model or settings.openai_model,
            "ocr_openai_configured": bool(settings.openai_api_key or os.environ.get("OPENAI_API_KEY")),
            "layout_profile": settings.document_profile,
            "model_mode": active,
            "openai_auth_mode": settings.llm_mode,
            "oauth_enabled": False,
            "oauth_provider": "local",
            "chatgpt_token_cache_path": "",
            "services": services,
        },
        "restart_required_hints": [],
    }


@router.post("/settings/validate", response_model=SettingsValidationResponse)
def validate_settings() -> dict:
    errors = validate_project_config()
    return {"ok": not errors, "validation_errors": errors, "restart_required_hints": []}


@router.post("/maintenance/clear-cache", response_model=MaintenanceResponse)
def clear_cache() -> dict:
    return {"ok": True, "affected_count": 0, "message": "当前缓存为空或无需清理。"}


@router.post("/maintenance/clear-all-cases", response_model=MaintenanceResponse)
def clear_all_cases(db: Annotated[Session, Depends(get_db)]) -> dict:
    count = len(db.execute(select(CaseRecord)).scalars().all())
    db.execute(delete(VisionFallbackRequestRecord))
    db.execute(delete(ModelCallRecord))
    db.execute(delete(ProcessingEventRecord))
    db.execute(delete(ProcessingRunRecord))
    db.execute(delete(ReviewAuditRecord))
    db.execute(delete(FieldResultRecord))
    db.execute(delete(CaseRecord))
    db.commit()
    uploads = settings.storage_dir / "uploads"
    if uploads.exists():
        shutil.rmtree(uploads, ignore_errors=True)
    return {"ok": True, "affected_count": count, "message": "全部病例已清空。"}
