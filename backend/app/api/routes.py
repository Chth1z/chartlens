from __future__ import annotations

import json
import os
import shutil
import hashlib
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.contracts import (
    AuthStatusResponse,
    BatchEvaluationResponse,
    CaseDiagnosticsResponse,
    ConfigResponse,
    DocumentIrResponse,
    EvaluationProfileRunResponse,
    FieldDictionaryResponse,
    FieldDictionarySettingsResponse,
    HealthResponse,
    MaintenanceResponse,
    ModelProfileSelectionResponse,
    ModelProfilesResponse,
    ModelProviderActivationResponse,
    ModelProviderFetchResponse,
    ModelProviderUpdateResponse,
    ModelProvidersResponse,
    ProjectConfigResponse,
    RuntimeSettingsResponse,
    SettingsValidationResponse,
    SystemSettingsResponse,
    VisionFallbackRecordResponse,
)
from app.core.config_loader import (
    list_ocr_profiles,
    load_evaluation_profile,
    load_export_template,
    load_extraction_schema,
    load_ocr_profile,
    validate_project_config,
)
from app.core.database import CaseRecord, FieldResultRecord, ReviewAuditRecord, get_case_or_none, get_db, json_loads
from app.core.settings import settings
from app.domain.models import CaseSummary, EvaluationRequest, EvaluationResult, ReviewDecision, ValidatedFieldResult
from app.services.diagnostics import build_case_diagnostics, frontend_evidence_config
from app.services.export import build_export_workbook
from app.services.model_selection import model_profiles_payload, set_active_model_profile
from app.services.ocr_accelerators import resolve_ocr_device_status
from app.services.model_providers import (
    ProviderSettingsUpdate,
    activate_provider_model,
    fetch_provider_models,
    provider_payload,
    update_provider,
)
from app.services.pipeline import create_case_record_from_saved_file, enqueue_case, prepare_case_file, process_case
from app.services.review import apply_review

router = APIRouter()
UPLOAD_CHUNK_SIZE = 1024 * 1024


class ModelSelectionPayload(BaseModel):
    profile_id: str


class ActiveProviderModelPayload(BaseModel):
    provider_id: str
    model_id: str


class BatchEvaluationCasePayload(BaseModel):
    case_id: str
    gold: dict[str, str]


class BatchEvaluationPayload(BaseModel):
    cases: list[BatchEvaluationCasePayload]


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


@router.get("/model-profiles", response_model=ModelProfilesResponse)
def get_model_profiles() -> dict:
    return model_profiles_payload()


@router.patch("/model-profiles/active", response_model=ModelProfileSelectionResponse)
def update_active_model_profile(payload: ModelSelectionPayload) -> dict:
    try:
        active = set_active_model_profile(payload.profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "active": active.model_dump(), **model_profiles_payload()}


@router.get("/model-providers", response_model=ModelProvidersResponse)
def get_model_providers() -> dict:
    return provider_payload()


@router.patch("/model-providers/active", response_model=ModelProviderActivationResponse)
def update_active_provider_model(payload: ActiveProviderModelPayload) -> dict:
    try:
        return activate_provider_model(payload.provider_id, payload.model_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/model-providers/{provider_id}", response_model=ModelProviderUpdateResponse)
def update_model_provider(provider_id: str, payload: ProviderSettingsUpdate) -> dict:
    try:
        return {"ok": True, "provider": update_provider(provider_id, payload)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/model-providers/{provider_id}/models/fetch", response_model=ModelProviderFetchResponse)
def fetch_models_for_provider(provider_id: str) -> dict:
    try:
        return fetch_provider_models(provider_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/cases", response_model=CaseSummary)
async def upload_case(file: Annotated[UploadFile, File()], db: Annotated[Session, Depends(get_db)]) -> CaseSummary:
    case = await _save_upload_as_case(file, db)
    if settings.auto_process_uploads:
        if not enqueue_case(case.case_id):
            file_parent = Path(case.file_path).parent
            db.delete(case)
            db.commit()
            _remove_upload_parent(file_parent)
            raise HTTPException(status_code=429, detail="Case processing queue is full; retry later")
    return _case_summary(case)


@router.get("/cases", response_model=list[CaseSummary])
def list_cases(db: Annotated[Session, Depends(get_db)]) -> list[CaseSummary]:
    cases = db.execute(select(CaseRecord).order_by(CaseRecord.created_at.desc())).scalars().all()
    return [_case_summary(case) for case in cases]


@router.get("/cases/{case_id}", response_model=CaseSummary)
def get_case(case_id: str, db: Annotated[Session, Depends(get_db)]) -> CaseSummary:
    case = _require_case(db, case_id)
    return _case_summary(case)


@router.post("/cases/{case_id}/reprocess", response_model=CaseSummary)
def reprocess_case(case_id: str, db: Annotated[Session, Depends(get_db)]) -> CaseSummary:
    case = _require_case(db, case_id)
    process_case(db, case)
    return _case_summary(case)


@router.get("/cases/{case_id}/document-ir", response_model=DocumentIrResponse)
def get_document_ir(case_id: str, db: Annotated[Session, Depends(get_db)]) -> dict:
    case = _require_case(db, case_id)
    return json.loads(case.document_ir_json) if case.document_ir_json else {"blocks": [], "sections": []}


@router.get("/cases/{case_id}/results", response_model=list[ValidatedFieldResult])
def get_results(case_id: str, db: Annotated[Session, Depends(get_db)]) -> list[ValidatedFieldResult]:
    _require_case(db, case_id)
    return _results_for_case(db, case_id)


@router.post("/cases/{case_id}/review", response_model=ValidatedFieldResult)
def review_field(case_id: str, decision: ReviewDecision, db: Annotated[Session, Depends(get_db)]) -> ValidatedFieldResult:
    _require_case(db, case_id)
    record = db.execute(
        select(FieldResultRecord).where(
            FieldResultRecord.case_id == case_id,
            FieldResultRecord.field_key == decision.field_key,
        )
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Field result not found")
    try:
        return apply_review(record, decision, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/cases/{case_id}/diagnostics", response_model=CaseDiagnosticsResponse)
def diagnostics(case_id: str, db: Annotated[Session, Depends(get_db)]) -> dict:
    case = _require_case(db, case_id)
    return build_case_diagnostics(case)


@router.get("/cases/{case_id}/export")
def export_case(case_id: str, db: Annotated[Session, Depends(get_db)]) -> Response:
    _require_case(db, case_id)
    data = build_export_workbook(_results_for_case(db, case_id))
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{case_id}.xlsx"'},
    )


@router.delete("/cases/{case_id}", response_model=MaintenanceResponse)
def delete_case(case_id: str, db: Annotated[Session, Depends(get_db)]) -> dict:
    case = _require_case(db, case_id)
    file_parent = None
    try:
        file_parent = Path(case.file_path).parent
    except Exception:
        file_parent = None
    db.delete(case)
    db.commit()
    if file_parent and file_parent.exists() and settings.storage_dir in file_parent.parents:
        shutil.rmtree(file_parent, ignore_errors=True)
    return {"ok": True, "affected_count": 1, "message": "病例已删除。"}


@router.post("/cases/{case_id}/vision-fallback-requests", response_model=VisionFallbackRecordResponse)
def vision_fallback_request(case_id: str, db: Annotated[Session, Depends(get_db)]) -> dict:
    _require_case(db, case_id)
    return {
        "request_id": f"vision-{case_id}",
        "case_id": case_id,
        "page": 1,
        "bbox": [],
        "status": "recorded",
        "reason": "manual redaction confirmed",
        "reviewer": "local-reviewer",
        "created_at": "",
        "approved_at": None,
    }


@router.get("/field-dictionary", response_model=FieldDictionaryResponse)
def field_dictionary() -> dict:
    schema = load_extraction_schema()
    return {"version": schema.version, "fields": [field.model_dump() for field in schema.fields]}


@router.get("/project-config", response_model=ProjectConfigResponse)
def project_config() -> dict:
    schema = load_extraction_schema()
    template = load_export_template()
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
            "default_document_profile_id": "medical_inpatient_zh",
            "default_extraction_schema_id": schema.schema_id,
            "default_export_template_id": template.template_id,
            "ocr_engine_policy": "intelligent_only",
        },
        "document_profile": {
            "profile_id": "medical_inpatient_zh",
            "version": "1.0.0",
            "label": "中文住院病例",
            "section_aliases": {},
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
            "layout_default_profile": "medical_inpatient_zh",
            "llm_default_profile": model_profiles_payload()["active_profile_id"],
            "ocr_profiles": [profile.profile_id for profile in list_ocr_profiles()],
            "layout_profiles": ["medical_inpatient_zh"],
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
            "layout_profile": "medical_inpatient_zh",
            "model_mode": active,
            "openai_auth_mode": settings.llm_mode,
            "oauth_enabled": False,
            "oauth_provider": "local",
            "chatgpt_token_cache_path": "",
        },
        "restart_required_hints": [],
    }


def _active_ocr_profile_payload() -> dict:
    try:
        return load_ocr_profile(settings.ocr_profile).model_dump()
    except Exception as exc:
        return {"profile_id": settings.ocr_profile, "label": settings.ocr_profile, "load_error": str(exc)}


def _runtime_ocr_engine_names(ocr_profile: dict) -> list[str]:
    engines = ocr_profile.get("engines", []) if isinstance(ocr_profile, dict) else []
    if isinstance(engines, list):
        return [
            str(engine.get("engine_id"))
            for engine in sorted(
                [item for item in engines if isinstance(item, dict) and item.get("enabled", True)],
                key=lambda item: int(item.get("priority", 100) or 100),
            )
            if engine.get("engine_id")
        ]
    return []


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
    db.execute(delete(ReviewAuditRecord))
    db.execute(delete(FieldResultRecord))
    db.execute(delete(CaseRecord))
    db.commit()
    uploads = settings.storage_dir / "uploads"
    if uploads.exists():
        shutil.rmtree(uploads, ignore_errors=True)
    return {"ok": True, "affected_count": count, "message": "全部病例已清空。"}


@router.post("/evals/runs", response_model=EvaluationResult)
def run_eval(request: EvaluationRequest, db: Annotated[Session, Depends(get_db)]) -> EvaluationResult:
    _require_case(db, request.case_id)
    results = {result.field_key: result for result in _results_for_case(db, request.case_id)}
    total = len(request.gold)
    correct = 0
    unknown_count = 0
    evidence_failures: list[str] = []
    for field_key, expected in request.gold.items():
        result = results.get(field_key)
        actual = result.normalized_code if result else None
        if actual == expected:
            correct += 1
        if actual in (None, "unknown"):
            unknown_count += 1
        if result and actual != "unknown" and not result.evidence_span:
            evidence_failures.append(field_key)
    return EvaluationResult(
        case_id=request.case_id,
        total=total,
        correct=correct,
        accuracy=correct / total if total else 0.0,
        unknown_count=unknown_count,
        missing_evidence_failures=evidence_failures,
    )


@router.post("/evals/batch", response_model=BatchEvaluationResponse)
def run_batch_eval(request: BatchEvaluationPayload, db: Annotated[Session, Depends(get_db)]) -> dict:
    case_results = [_eval_case(item.case_id, item.gold, db) for item in request.cases]
    summary = _summarize_eval_cases(case_results)
    return {"summary": summary, "cases": case_results}


@router.post("/evals/profiles/{profile_id}/run", response_model=EvaluationProfileRunResponse)
def run_evaluation_profile(profile_id: str, db: Annotated[Session, Depends(get_db)]) -> dict:
    try:
        profile = load_evaluation_profile(profile_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Evaluation profile not found") from None
    case_results = [_eval_case(item.case_id, item.gold, db, tags=item.tags) for item in profile.gold_cases]
    summary = _summarize_eval_cases(case_results, field_tags=profile.field_tags)
    return {
        "profile": {
            "profile_id": profile.profile_id,
            "label": profile.label,
            "schema_id": profile.schema_id,
            "thresholds": profile.thresholds,
            "token_budget": profile.token_budget,
        },
        "summary": summary,
        "cases": case_results,
    }


def _require_case(db: Session, case_id: str) -> CaseRecord:
    case = get_case_or_none(db, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


def _eval_case(case_id: str, gold: dict[str, str], db: Session, *, tags: list[str] | None = None) -> dict:
    case = _require_case(db, case_id)
    results = {result.field_key: result for result in _results_for_case(db, case_id)}
    field_metrics = []
    correct = 0
    predicted_non_unknown = 0
    gold_non_unknown = 0
    true_positive = 0
    expected_unknown = 0
    unknown_misfills = 0
    evidence_covered = 0
    auto_accept_count = 0
    auto_accept_correct = 0
    for field_key, expected in gold.items():
        result = results.get(field_key)
        actual = result.normalized_code if result else None
        is_correct = actual == expected
        correct += int(is_correct)
        if expected != "unknown":
            gold_non_unknown += 1
        else:
            expected_unknown += 1
        if actual not in (None, "unknown"):
            predicted_non_unknown += 1
            evidence_covered += int(bool(result and result.evidence_span and result.evidence_block_id))
            if expected == "unknown":
                unknown_misfills += 1
        if actual == expected and expected != "unknown":
            true_positive += 1
        if result and result.auto_accepted:
            auto_accept_count += 1
            auto_accept_correct += int(is_correct)
        field_metrics.append(
            {
                "field_key": field_key,
                "expected": expected,
                "actual": actual,
                "correct": is_correct,
                "auto_accepted": bool(result.auto_accepted) if result else False,
                "has_evidence": bool(result and result.evidence_span and result.evidence_block_id),
                "review_required": bool(result.review_required) if result else True,
                "error_code": result.error_code if result else "MISSING_RESULT",
            }
        )
    diagnostics = json_loads(case.diagnostics_json, {})
    usage = _usage_totals(diagnostics)
    total = len(gold)
    return {
        "case_id": case_id,
        "total_fields": total,
        "correct": correct,
        "accuracy": correct / total if total else 0.0,
        "precision": true_positive / predicted_non_unknown if predicted_non_unknown else 0.0,
        "recall": true_positive / gold_non_unknown if gold_non_unknown else 0.0,
        "auto_accept_count": auto_accept_count,
        "auto_accept_correct": auto_accept_correct,
        "auto_accept_precision": auto_accept_correct / auto_accept_count if auto_accept_count else 0.0,
        "unknown_misfills": unknown_misfills,
        "expected_unknown": expected_unknown,
        "unknown_misfill_rate": unknown_misfills / expected_unknown if expected_unknown else 0.0,
        "predicted_non_unknown": predicted_non_unknown,
        "evidence_covered": evidence_covered,
        "evidence_coverage": evidence_covered / predicted_non_unknown if predicted_non_unknown else 1.0,
        "usage": usage,
        "tags": tags or [],
        "ocr_quality": _case_ocr_quality(case),
        "fields": field_metrics,
    }


def _summarize_eval_cases(case_results: list[dict], *, field_tags: dict[str, list[str]] | None = None) -> dict:
    totals = {
        "total_fields": sum(item["total_fields"] for item in case_results),
        "correct": sum(item["correct"] for item in case_results),
        "auto_accept_count": sum(item["auto_accept_count"] for item in case_results),
        "auto_accept_correct": sum(item["auto_accept_correct"] for item in case_results),
        "unknown_misfills": sum(item["unknown_misfills"] for item in case_results),
        "expected_unknown": sum(item["expected_unknown"] for item in case_results),
        "predicted_non_unknown": sum(item["predicted_non_unknown"] for item in case_results),
        "evidence_covered": sum(item["evidence_covered"] for item in case_results),
        "input_tokens": sum(item["usage"]["input_tokens"] for item in case_results),
        "output_tokens": sum(item["usage"]["output_tokens"] for item in case_results),
        "cost_usd": sum(item["usage"]["cost_usd"] for item in case_results),
    }
    auto_accept_count = totals["auto_accept_count"]
    field_tag_summary = _field_tag_summary(case_results, field_tags or {})
    quality_bands = _ocr_quality_band_counts(case_results)
    return {
        **totals,
        "case_count": len(case_results),
        "accuracy": totals["correct"] / totals["total_fields"] if totals["total_fields"] else 0.0,
        "auto_accept_precision": (
            totals["auto_accept_correct"] / totals["auto_accept_count"] if totals["auto_accept_count"] else 0.0
        ),
        "unknown_misfill_rate": (
            totals["unknown_misfills"] / totals["expected_unknown"] if totals["expected_unknown"] else 0.0
        ),
        "evidence_coverage": (
            totals["evidence_covered"] / totals["predicted_non_unknown"] if totals["predicted_non_unknown"] else 1.0
        ),
        "tokens_per_case": totals["input_tokens"] / len(case_results) if case_results else 0.0,
        "tokens_per_accepted_field": totals["input_tokens"] / auto_accept_count if auto_accept_count else 0.0,
        "field_tags": field_tag_summary,
        "ocr_quality_bands": quality_bands,
    }


def _field_tag_summary(case_results: list[dict], field_tags: dict[str, list[str]]) -> dict:
    buckets: dict[str, dict[str, int]] = {}
    for case in case_results:
        for field in case.get("fields", []):
            tags = field_tags.get(field.get("field_key"), [])
            for tag in tags:
                bucket = buckets.setdefault(tag, {"total": 0, "correct": 0, "auto_accept_count": 0, "auto_accept_correct": 0})
                bucket["total"] += 1
                bucket["correct"] += int(bool(field.get("correct")))
                if field.get("auto_accepted"):
                    bucket["auto_accept_count"] += 1
                    bucket["auto_accept_correct"] += int(bool(field.get("correct")))
    return {
        tag: {
            **bucket,
            "accuracy": bucket["correct"] / bucket["total"] if bucket["total"] else 0.0,
            "auto_accept_precision": (
                bucket["auto_accept_correct"] / bucket["auto_accept_count"] if bucket["auto_accept_count"] else 0.0
            ),
        }
        for tag, bucket in buckets.items()
    }


def _ocr_quality_band_counts(case_results: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for case in case_results:
        band = str(case.get("ocr_quality", {}).get("quality_band") or "unknown")
        counts[band] = counts.get(band, 0) + 1
    return counts


def _case_ocr_quality(case: CaseRecord) -> dict:
    document = json.loads(case.document_ir_json) if case.document_ir_json else {"blocks": [], "metadata": {}}
    diagnostics = json_loads(case.diagnostics_json, {})
    metadata = document.get("metadata", {}) if isinstance(document, dict) else {}
    quality = diagnostics.get("quality", {}) if isinstance(diagnostics, dict) else {}
    return {
        "quality_band": quality.get("quality_band") or metadata.get("quality_band") or "unknown",
        "page_quality": metadata.get("ocr_page_quality", []),
        "ocr_engine": metadata.get("ocr_engine") or quality.get("ocr_engine"),
        "ocr_cache_status": metadata.get("ocr_cache_status") or quality.get("ocr_cache_status"),
    }


def _usage_totals(diagnostics: dict) -> dict:
    totals = {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0, "cost_usd": 0.0}
    for item in diagnostics.get("llm_usage", []):
        usage = item.get("usage", {}) if isinstance(item, dict) else {}
        totals["input_tokens"] += int(usage.get("input_tokens", 0) or 0)
        totals["output_tokens"] += int(usage.get("output_tokens", 0) or 0)
        totals["cached_input_tokens"] += int(usage.get("cached_input_tokens", 0) or 0)
        totals["cost_usd"] += float(usage.get("cost_usd", 0.0) or 0.0)
    return totals


async def _save_upload_as_case(file: UploadFile, db: Session) -> CaseRecord:
    filename = file.filename or "case.txt"
    suffix = Path(filename).suffix.lower()
    if suffix not in _allowed_upload_suffixes():
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {suffix or '<none>'}")

    case_id, safe_name, file_path = prepare_case_file(filename)
    digest = hashlib.sha256()
    total_bytes = 0
    try:
        with file_path.open("wb") as output:
            while True:
                chunk = await file.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > settings.max_upload_bytes:
                    raise HTTPException(status_code=413, detail="Uploaded file exceeds the configured size limit")
                digest.update(chunk)
                output.write(chunk)
        if total_bytes == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        return create_case_record_from_saved_file(db, case_id, safe_name, file_path, digest.hexdigest())
    except Exception:
        _remove_upload_parent(file_path.parent)
        raise


def _allowed_upload_suffixes() -> set[str]:
    return {
        item.strip().lower()
        for item in settings.allowed_upload_suffixes.split(",")
        if item.strip()
    }


def _remove_upload_parent(file_parent: Path) -> None:
    try:
        if file_parent.exists() and settings.storage_dir in file_parent.parents:
            shutil.rmtree(file_parent, ignore_errors=True)
    except Exception:
        return


def _results_for_case(db: Session, case_id: str) -> list[ValidatedFieldResult]:
    records = db.execute(
        select(FieldResultRecord).where(FieldResultRecord.case_id == case_id).order_by(FieldResultRecord.field_key)
    ).scalars()
    return [ValidatedFieldResult.model_validate_json(record.payload_json) for record in records]


def _case_summary(case: CaseRecord) -> CaseSummary:
    result_count = len(case.results)
    review_required_count = 0
    for record in case.results:
        result = ValidatedFieldResult.model_validate_json(record.payload_json)
        if result.review_required:
            review_required_count += 1
    return CaseSummary(
        case_id=case.case_id,
        filename=case.filename,
        status=case.status,
        created_at=case.created_at,
        updated_at=case.updated_at,
        result_count=result_count,
        review_required_count=review_required_count,
    )


def _online_model_available() -> bool:
    payload = model_profiles_payload()
    active = next((profile for profile in payload["profiles"] if profile["profile_id"] == payload["active_profile_id"]), None)
    if not active:
        return False
    if active["provider"] == "disabled":
        return False
    return bool(active.get("auth_configured"))


def _active_provider_label() -> str:
    payload = model_profiles_payload()
    active = next((profile for profile in payload["profiles"] if profile["profile_id"] == payload["active_profile_id"]), None)
    if not active:
        return "local_fallback"
    if active["provider"] == "disabled":
        return "local_fallback"
    return active.get("provider_id") or active["provider"]


def _active_api_key_configured() -> bool:
    return _online_model_available()
