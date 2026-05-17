from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy.orm import Session

from app.core.database import CaseRecord, ModelCallRecord, ProcessingEventRecord, ProcessingRunRecord, json_dumps
from app.core.settings import settings
from app.domain.models import DocumentIR, FieldDefinition, ValidatedFieldResult
from app.services.model_selection import model_profiles_payload
from app.services.safe_errors import safe_error_message


class ProcessingTrace:
    def __init__(self, db: Session, run: ProcessingRunRecord) -> None:
        self.db = db
        self.run = run
        self._started_perf = time.perf_counter()

    @classmethod
    def start(cls, db: Session, case: CaseRecord) -> "ProcessingTrace":
        run = ProcessingRunRecord(
            run_id=f"run-{case.case_id}-{uuid.uuid4().hex[:10]}",
            case_id=case.case_id,
            status="started",
            config_snapshot_json=json_dumps(_config_snapshot()),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return cls(db, run)

    @contextmanager
    def step(self, name: str, payload: dict[str, Any] | None = None) -> Iterator[ProcessingEventRecord]:
        started_perf = time.perf_counter()
        event = ProcessingEventRecord(
            run_id=self.run.run_id,
            case_id=self.run.case_id,
            step_name=name,
            status="started",
            payload_json=json_dumps(_safe_payload(payload or {})),
        )
        self.db.add(event)
        self.db.commit()
        try:
            yield event
        except Exception as exc:
            _complete_event(event, started_perf, status="failed", error_code=type(exc).__name__, error_message=_safe_exception_summary(exc))
            self.db.add(event)
            self.db.commit()
            raise
        else:
            _complete_event(event, started_perf, status="completed")
            self.db.add(event)
            self.db.commit()

    def record_model_call(
        self,
        *,
        stage: str,
        provider: Any,
        fields: list[FieldDefinition],
        usage: dict[str, Any] | None = None,
        started_perf: float | None = None,
        status: str = "completed",
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        usage = usage or {}
        profile = getattr(provider, "profile", None)
        provider_name = str(getattr(provider, "name", "unknown"))
        model = usage.get("model") or getattr(provider, "model", None) or getattr(profile, "model", None) or provider_name
        duration_ms = _elapsed_ms(started_perf) if started_perf is not None else _optional_int(usage.get("latency_ms"))
        record = ModelCallRecord(
            call_id=f"call-{self.run.run_id}-{uuid.uuid4().hex[:8]}",
            run_id=self.run.run_id,
            case_id=self.run.case_id,
            stage=stage,
            provider=provider_name,
            model=str(model or "unknown"),
            mode=str(getattr(provider, "route", "unknown")),
            field_keys_json=json_dumps([field.key for field in fields]),
            input_tokens=_int_value(usage.get("input_tokens")),
            cached_input_tokens=_int_value(usage.get("cached_input_tokens")),
            output_tokens=_int_value(usage.get("output_tokens")),
            cost_usd=float(usage.get("cost_usd") or 0.0),
            duration_ms=duration_ms,
            status=status,
            error_code=error_code,
            error_message=safe_error_message(error_message, limit=500) if error_message else None,
            fallback_attempts=_int_value(usage.get("fallback_attempts")),
            fallback_failures=_int_value(usage.get("fallback_failures")),
            fallback_errors_json=json_dumps(_safe_payload(usage.get("fallback_errors") or [])),
            llm_cache_status=_optional_str(usage.get("llm_cache_status")),
            llm_cache_key=_optional_str(usage.get("llm_cache_key")),
        )
        self.db.add(record)
        self.db.commit()

    def finish_completed(
        self,
        *,
        results: list[ValidatedFieldResult],
        document_ir: DocumentIR,
        diagnostics: dict,
    ) -> None:
        quality = diagnostics.get("quality") if isinstance(diagnostics.get("quality"), dict) else {}
        self.run.status = "completed"
        self.run.quality_json = json_dumps(_safe_payload(quality))
        self.run.page_count = len({block.page for block in document_ir.blocks})
        self.run.ocr_block_count = len(document_ir.blocks)
        self.run.result_count = len(results)
        self.run.auto_accept_count = len([result for result in results if result.auto_accepted])
        self.run.review_required_count = len([result for result in results if result.review_required])
        self.run.unknown_count = len([result for result in results if result.normalized_code in (None, "unknown")])
        self.run.completed_at = datetime.now(timezone.utc)
        self.run.duration_ms = _elapsed_ms(self._started_perf)
        self.db.add(self.run)
        self.db.commit()

    def finish_failed(self, *, diagnostics: dict) -> None:
        self.run.status = "failed"
        self.run.error_code = _optional_str(diagnostics.get("error_code")) or "PROCESSING_FAILED"
        self.run.error_message = _optional_str(diagnostics.get("error")) or "processing failed"
        self.run.completed_at = datetime.now(timezone.utc)
        self.run.duration_ms = _elapsed_ms(self._started_perf)
        self.db.add(self.run)
        self.db.commit()


def _complete_event(
    event: ProcessingEventRecord,
    started_perf: float,
    *,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    event.status = status
    event.error_code = error_code
    event.error_message = error_message
    event.completed_at = datetime.now(timezone.utc)
    event.duration_ms = _elapsed_ms(started_perf)


def _config_snapshot() -> dict[str, Any]:
    active_model = model_profiles_payload()["active_profile_id"]
    return {
        "database_url": settings.database_url,
        "storage_dir": str(settings.storage_dir),
        "config_dir": str(settings.config_dir),
        "document_profile": settings.document_profile,
        "ocr_profile": settings.ocr_profile,
        "extraction_schema": settings.extraction_schema,
        "export_template": settings.export_template,
        "model_profile": active_model,
        "llm_mode": settings.llm_mode,
        "ocr_strategy": settings.ocr_strategy,
        "ocr_route_version": settings.ocr_route_version,
    }


def _safe_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _safe_value(str(key), item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_payload(item) for item in value]
    return _safe_scalar(value)


def _safe_value(key: str, value: Any) -> Any:
    normalized = key.lower()
    if any(marker in normalized for marker in ("api_key", "token", "secret", "password", "authorization")):
        return "***"
    if normalized in {"file_path", "path", "source_path"}:
        return Path(str(value)).name if value else ""
    return _safe_payload(value)


def _safe_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    text = str(value)
    if len(text) > 2000:
        return f"{text[:2000]}...<truncated>"
    return text


def _safe_exception_summary(exc: Exception) -> str:
    text = safe_error_message(exc, limit=300)
    if not text or isinstance(exc, (FileNotFoundError, PermissionError)):
        return f"{type(exc).__name__}: step failed"
    if "\\" in text or "/" in text:
        return f"{type(exc).__name__}: step failed"
    return f"{type(exc).__name__}: {text}"


def _elapsed_ms(started_perf: float) -> int:
    return max(0, int(round((time.perf_counter() - started_perf) * 1000)))


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return _int_value(value)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
