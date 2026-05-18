from __future__ import annotations

from app.core.config_loader import load_extraction_schema
from app.core.database import (
    CaseRecord,
    ModelCallRecord,
    ProcessingRunRecord,
    VisionFallbackRequestRecord,
    json_loads,
)
from app.core.settings import settings
from app.domain.models import ValidatedFieldResult
from app.services.model_selection import model_profiles_payload


def processing_run(case: CaseRecord) -> dict:
    # Lazy import to avoid module-level circular dependency with case_summary.
    from app.services.diagnostics.case_summary import quality_summary

    results = [ValidatedFieldResult.model_validate_json(record.payload_json) for record in case.results]
    quality = quality_summary(case)
    diagnostics_payload = json_loads(case.diagnostics_json, {})
    usage = diagnostics_payload.get("llm_usage", [{}])
    first_usage = usage[0].get("usage", {}) if usage else {}
    page_quality = quality.get("ocr_page_quality") or []
    return {
        "run_id": f"run-{case.case_id}",
        "status": case.status,
        "system_config_version": "1.0.0",
        "field_dictionary_version": load_extraction_schema().version,
        "ocr_profile": settings.ocr_profile,
        "layout_profile": "medical_inpatient_zh",
        "llm_profile": model_profiles_payload()["active_profile_id"],
        "parser_mode": "document_ir",
        "page_count": quality["page_count"],
        "ocr_block_count": quality["ocr_block_count"],
        "fragment_count": quality["fragment_count"],
        "avg_ocr_confidence": quality["avg_ocr_confidence"],
        "low_confidence_block_count": quality["low_confidence_block_count"],
        "quality_band": quality["quality_band"],
        "auto_accept_count": len([result for result in results if result.auto_accepted]),
        "review_required_count": len([result for result in results if result.review_required]),
        "unknown_count": len([result for result in results if result.normalized_code == "unknown"]),
        "input_tokens": first_usage.get("input_tokens", 0),
        "cached_input_tokens": first_usage.get("cached_input_tokens", 0),
        "output_tokens": first_usage.get("output_tokens", 0),
        "cost_usd": first_usage.get("cost_usd", 0),
        "latency_ms": 0,
        "step_timings": {
            "ocr_ms": 0,
            "layout_ms": 0,
            "extract_ms": 0,
            "persist_ms": 0,
            "rule_ms": 0,
            "llm_call_count": len(usage),
            "layout_provider": quality.get("ocr_engine") or "intelligent_document",
            "ocr_adapter": quality.get("ocr_adapter") or "intelligent_document",
            "ocr_engine": quality.get("ocr_engine") or "none",
            "ocr_intelligent_status": quality.get("ocr_intelligent_status") or "",
            "ocr_attempted_engine_count": len(quality.get("ocr_attempted_engines") or []),
            "ocr_unavailable_engine_count": len(quality.get("ocr_unavailable_engines") or []),
            "ocr_unavailable_reasons": quality.get("ocr_unavailable_reasons") or {},
            "ocr_engine_errors": quality.get("ocr_engine_errors") or {},
            "ocr_trace_total_ms": _trace_total_ms(quality.get("ocr_trace")),
            "ocr_trace_stage_count": _trace_stage_count(quality.get("ocr_trace")),
            "ocr_timed_out_stage_count": _trace_status_count(quality.get("ocr_trace"), "timeout"),
            "ocr_failed_stage_count": _trace_status_count(quality.get("ocr_trace"), "failed"),
            "ocr_selected_engine": _trace_selected_engine(quality.get("ocr_trace"), quality.get("ocr_engine")),
            "ocr_slowest_stage": _trace_slowest_stage_name(quality.get("ocr_trace")),
            "ocr_slowest_stage_ms": _trace_slowest_stage_ms(quality.get("ocr_trace")),
            "ocr_trace_error": _trace_error(quality.get("ocr_trace")),
            "page_cache_hit_count": len([item for item in page_quality if item.get("cache_status") == "hit"]),
            "low_quality_page_count": len([item for item in page_quality if item.get("quality_band") == "poor"]),
            "llm_skipped_no_evidence_count": len([result for result in results if result.error_code == "NO_EVIDENCE_CANDIDATES_SKIPPED_LLM"]),
            "llm_cache_hit_count": len([item for item in usage if item.get("usage", {}).get("llm_cache_status") == "hit"]),
        },
        "error_message": diagnostics_payload.get("error"),
        "created_at": case.created_at.isoformat(),
        "completed_at": case.updated_at.isoformat() if case.status in {"completed", "failed"} else None,
    }


def _run_record_payload(run: ProcessingRunRecord, case: CaseRecord) -> dict:
    config = json_loads(run.config_snapshot_json, {})
    quality = json_loads(run.quality_json, {})
    calls = list(run.model_calls)
    page_quality = quality.get("ocr_page_quality") or []
    return {
        "run_id": run.run_id,
        "status": run.status,
        "system_config_version": "1.0.0",
        "field_dictionary_version": load_extraction_schema().version,
        "ocr_profile": config.get("ocr_profile") or settings.ocr_profile,
        "layout_profile": config.get("document_profile") or settings.document_profile,
        "llm_profile": config.get("model_profile") or model_profiles_payload()["active_profile_id"],
        "parser_mode": "document_ir",
        "page_count": run.page_count,
        "ocr_block_count": run.ocr_block_count,
        "fragment_count": run.ocr_block_count,
        "avg_ocr_confidence": quality.get("avg_ocr_confidence", 0),
        "low_confidence_block_count": quality.get("low_confidence_block_count", 0),
        "quality_band": quality.get("quality_band", "unknown"),
        "auto_accept_count": run.auto_accept_count,
        "review_required_count": run.review_required_count,
        "unknown_count": run.unknown_count,
        "input_tokens": sum(call.input_tokens for call in calls),
        "cached_input_tokens": sum(call.cached_input_tokens for call in calls),
        "output_tokens": sum(call.output_tokens for call in calls),
        "cost_usd": sum(call.cost_usd for call in calls),
        "latency_ms": run.duration_ms or 0,
        "step_timings": _step_timings(run, calls, page_quality, quality),
        "error_message": run.error_message,
        "created_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


def _step_timings(run: ProcessingRunRecord, calls: list[ModelCallRecord], page_quality: list[dict], quality: dict) -> dict:
    timings = {f"{event.step_name}_ms": event.duration_ms or 0 for event in run.events}
    layout_ms = timings.get("normalize_document_layout_ms", 0) + timings.get("build_document_context_ms", 0)
    extract_ms = timings.get("extract_document_ms", 0)
    ocr_trace = quality.get("ocr_trace", {})
    timings.update(
        {
            "ocr_ms": timings.get("ocr_document_ir_ms", 0),
            "layout_ms": layout_ms,
            "extract_ms": extract_ms,
            "persist_ms": timings.get("persist_results_ms", 0),
            "rule_ms": extract_ms,
            "llm_call_count": len(calls),
            "layout_provider": quality.get("ocr_engine") or "intelligent_document",
            "ocr_adapter": quality.get("ocr_adapter") or "intelligent_document",
            "ocr_engine": quality.get("ocr_engine") or "none",
            "ocr_intelligent_status": quality.get("ocr_intelligent_status") or "",
            "ocr_attempted_engine_count": len(quality.get("ocr_attempted_engines") or []),
            "ocr_unavailable_engine_count": len(quality.get("ocr_unavailable_engines") or []),
            "ocr_unavailable_reasons": quality.get("ocr_unavailable_reasons") or {},
            "ocr_engine_errors": quality.get("ocr_engine_errors") or {},
            "ocr_trace_total_ms": _trace_total_ms(ocr_trace),
            "ocr_trace_stage_count": _trace_stage_count(ocr_trace),
            "ocr_timed_out_stage_count": _trace_status_count(ocr_trace, "timeout"),
            "ocr_failed_stage_count": _trace_status_count(ocr_trace, "failed"),
            "ocr_selected_engine": _trace_selected_engine(ocr_trace, quality.get("ocr_engine")),
            "ocr_slowest_stage": _trace_slowest_stage_name(ocr_trace),
            "ocr_slowest_stage_ms": _trace_slowest_stage_ms(ocr_trace),
            "ocr_trace_error": _trace_error(ocr_trace),
            "page_cache_hit_count": len([item for item in page_quality if item.get("cache_status") == "hit"]),
            "low_quality_page_count": len([item for item in page_quality if item.get("quality_band") == "poor"]),
            "llm_skipped_no_evidence_count": _count_skipped_no_evidence(calls),
            "llm_cache_hit_count": len([call for call in calls if call.llm_cache_status == "hit"]),
        }
    )
    return timings


def _count_skipped_no_evidence(calls: list[ModelCallRecord]) -> int:
    count = 0
    for call in calls:
        field_keys = json_loads(call.field_keys_json, [])
        if call.stage == "collect_evidence" and not field_keys:
            continue
        if call.error_code == "NO_EVIDENCE_CANDIDATES_SKIPPED_LLM":
            count += max(1, len(field_keys))
    return count


def _trace_total_ms(trace: object) -> int:
    if not isinstance(trace, dict):
        return 0
    try:
        return int(round(float(trace.get("total_duration_ms") or 0)))
    except Exception:
        return 0


def _trace_stage_count(trace: object) -> int:
    if not isinstance(trace, dict):
        return 0
    stages = trace.get("stages")
    return len(stages) if isinstance(stages, list) else 0


def _trace_status_count(trace: object, status: str) -> int:
    if not isinstance(trace, dict):
        return 0
    stages = trace.get("stages")
    if not isinstance(stages, list):
        return 0
    return len([stage for stage in stages if isinstance(stage, dict) and stage.get("status") == status])


def _trace_selected_engine(trace: object, fallback_engine: object) -> str:
    if isinstance(trace, dict):
        value = trace.get("selected_engine")
        if isinstance(value, str) and value.strip():
            return value
    return str(fallback_engine or "none")


def _trace_slowest_stage_name(trace: object) -> str:
    stage = _trace_slowest_stage(trace)
    if not stage:
        return ""
    value = stage.get("engine") or stage.get("stage") or ""
    return str(value)


def _trace_slowest_stage_ms(trace: object) -> int:
    stage = _trace_slowest_stage(trace)
    if not stage:
        return 0
    try:
        return int(round(float(stage.get("duration_ms") or 0)))
    except Exception:
        return 0


def _trace_error(trace: object) -> str:
    if not isinstance(trace, dict):
        return ""
    value = trace.get("error")
    return str(value) if value else ""


def _trace_slowest_stage(trace: object) -> dict | None:
    if not isinstance(trace, dict):
        return None
    stages = trace.get("stages")
    if not isinstance(stages, list):
        return None
    candidates = [stage for stage in stages if isinstance(stage, dict)]
    if not candidates:
        return None
    return max(candidates, key=lambda stage: float(stage.get("duration_ms") or 0))


def _model_call_payload(call: ModelCallRecord) -> dict:
    return {
        "call_id": call.call_id,
        "run_id": call.run_id,
        "provider": call.provider,
        "model": call.model,
        "mode": call.mode,
        "stage": call.stage,
        "field_keys": json_loads(call.field_keys_json, []),
        "input_tokens": call.input_tokens,
        "cached_input_tokens": call.cached_input_tokens,
        "output_tokens": call.output_tokens,
        "cost_usd": call.cost_usd,
        "latency_ms": call.duration_ms or 0,
        "status": call.status,
        "error_code": call.error_code,
        "error_message": call.error_message,
        "fallback_attempts": call.fallback_attempts,
        "fallback_failures": call.fallback_failures,
        "fallback_errors": json_loads(call.fallback_errors_json, []),
        "llm_cache_status": call.llm_cache_status,
        "llm_cache_key": call.llm_cache_key,
        "created_at": call.created_at.isoformat(),
    }


def _event_payload(event) -> dict:
    return {
        "run_id": event.run_id,
        "step_name": event.step_name,
        "status": event.status,
        "payload": json_loads(event.payload_json, {}),
        "error_code": event.error_code,
        "error_message": event.error_message,
        "duration_ms": event.duration_ms or 0,
        "started_at": event.started_at.isoformat(),
        "completed_at": event.completed_at.isoformat() if event.completed_at else None,
    }


def _vision_request_payload(request: VisionFallbackRequestRecord) -> dict:
    return {
        "request_id": request.request_id,
        "case_id": request.case_id,
        "field_key": request.field_key,
        "page": request.page,
        "bbox": json_loads(request.bbox_json, []),
        "status": request.status,
        "reason": request.reason,
        "reviewer": request.reviewer,
        "manual_redaction_confirmed": bool(request.manual_redaction_confirmed),
        "created_at": request.created_at.isoformat(),
        "approved_at": request.approved_at.isoformat() if request.approved_at else None,
    }
