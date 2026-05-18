"""Internal helpers shared across the API route modules.

These functions are private to the `app.api.routes` package and intentionally
keep the same names (and prefixed underscores) they had in the pre-split
`backend/app/api/routes.py`. Route modules import from here; this module must
not import from any sibling route module to avoid circular imports.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config_loader import load_ocr_profile
from app.core.database import (
    CaseRecord,
    FieldResultRecord,
    VisionFallbackRequestRecord,
    get_case_or_none,
    json_loads,
)
from app.core.settings import settings
from app.domain.models import CaseSummary, ValidatedFieldResult
from app.services.extraction_eval import evaluate_case_against_gold
from app.services.model_selection import model_profiles_payload
from app.services.pipeline import create_case_record_from_saved_file, prepare_case_file
from app.services.secret_store import unprotect_text
from app.services.source_pages import (
    case_document_metadata as _source_case_document_metadata,
    case_document_payload as _source_case_document_payload,
    case_page_render_dpi as _source_case_page_render_dpi,
    pdf_source_render_scale,
    positive_float as _source_positive_float,
)


UPLOAD_CHUNK_SIZE = 1024 * 1024


def _require_case(db: Session, case_id: str) -> CaseRecord:
    case = get_case_or_none(db, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


def _pdf_source_render_scale(case: CaseRecord, page: int) -> float:
    return pdf_source_render_scale(case, page)


def _case_document_payload(case: CaseRecord) -> dict:
    return _source_case_document_payload(case)


def _case_raw_document_payload(case: CaseRecord) -> dict:
    if not case.raw_document_ir_json:
        return {}
    protected = json_loads(case.raw_document_ir_json, {})
    if not isinstance(protected, dict):
        return {}
    raw = unprotect_text(protected)
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _case_document_metadata(case: CaseRecord) -> dict:
    return _source_case_document_metadata(case)


def _case_page_render_dpi(case: CaseRecord, page: int) -> float | None:
    return _source_case_page_render_dpi(case, page)


def _positive_float(value: object) -> float | None:
    return _source_positive_float(value)


def _eval_case(case_id: str, gold: dict[str, str], db: Session, *, tags: list[str] | None = None) -> dict:
    """Backward-compatible shim. Prefer `services.extraction_eval.evaluate_case_against_gold`."""
    return evaluate_case_against_gold(case_id, gold, db, tags=tags)


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
        audit_count=len(case.audits),
    )


def _vision_fallback_record_payload(record: VisionFallbackRequestRecord) -> dict:
    return {
        "request_id": record.request_id,
        "case_id": record.case_id,
        "field_key": record.field_key,
        "page": record.page,
        "bbox": json_loads(record.bbox_json, []),
        "status": record.status,
        "reason": record.reason,
        "reviewer": record.reviewer,
        "manual_redaction_confirmed": bool(record.manual_redaction_confirmed),
        "created_at": record.created_at.isoformat(),
        "approved_at": record.approved_at.isoformat() if record.approved_at else None,
    }


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


def _config_rule_ids() -> list[str]:
    path = settings.config_dir / "validation_rules"
    if not path.exists():
        return []
    return [item.stem for item in sorted(path.glob("*.yaml"))]
