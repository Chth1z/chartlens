from __future__ import annotations

import json
import re

from app.core.config_loader import load_extraction_schema
from app.core.database import CaseRecord, json_loads
from app.core.settings import settings
from app.domain.models import ValidatedFieldResult
from app.services.model_selection import model_profiles_payload


def build_case_diagnostics(case: CaseRecord) -> dict:
    document = json.loads(case.document_ir_json) if case.document_ir_json else {"blocks": []}
    diagnostics_payload = json_loads(case.diagnostics_json, {})
    fragments = [
        {
            "page": block.get("page", 1),
            "reading_order": block.get("reading_order", index + 1),
            "text": block.get("text", ""),
            "bbox": block.get("bbox", []),
            "confidence": block.get("confidence", 0),
            "section_name": block.get("section_label", "智能文档解析"),
            "block_type": block.get("block_type", "paragraph"),
            "source_engine": block.get("source_engine"),
            "source_page_kind": block.get("source_page_kind", "unknown"),
            "ocr_profile": block.get("ocr_profile"),
            "layout_profile": block.get("layout_profile"),
            "quality_flags": block.get("quality_flags", []),
            "model_name": block.get("model_name"),
            "model_version": block.get("model_version"),
            "accelerator": block.get("accelerator"),
            "engine_version": block.get("engine_version"),
            "route_profile_id": block.get("route_profile_id"),
            "source_kind": "intelligent_document",
            "document_kind": block.get("document_kind", "unknown"),
            "layout_region_id": block.get("section_id"),
            "layout_type": block.get("block_type", "paragraph"),
            "section_confidence": block.get("confidence", 0),
            "parser_version": "eyex-v1",
        }
        for index, block in enumerate(document.get("blocks", []))
    ]
    model_calls = [
        {
            "call_id": f"call-{index}",
            "provider": item.get("provider", "local_fallback"),
            "model": item.get("model") or item.get("provider", "local"),
            "mode": item.get("route", "local"),
            "field_keys": item.get("field_keys", []),
            "input_tokens": item.get("usage", {}).get("input_tokens", 0),
            "cached_input_tokens": item.get("usage", {}).get("cached_input_tokens", 0),
            "output_tokens": item.get("usage", {}).get("output_tokens", 0),
            "cost_usd": item.get("usage", {}).get("cost_usd", 0),
            "latency_ms": item.get("latency_ms", 0),
            "status": item.get("status", "completed"),
            "error_code": item.get("error_code"),
            "fallback_attempts": item.get("usage", {}).get("fallback_attempts", 0),
            "fallback_failures": item.get("usage", {}).get("fallback_failures", 0),
            "fallback_errors": item.get("usage", {}).get("fallback_errors", []),
            "llm_cache_status": item.get("usage", {}).get("llm_cache_status"),
            "llm_cache_key": item.get("usage", {}).get("llm_cache_key"),
            "created_at": case.updated_at.isoformat(),
        }
        for index, item in enumerate(diagnostics_payload.get("llm_usage", []), start=1)
    ]
    latest_run = processing_run(case)
    return {
        "case_id": case.case_id,
        "quality": quality_summary(case),
        "latest_run": latest_run,
        "run_count": 1 if latest_run else 0,
        "runs": [latest_run] if latest_run else [],
        "fragments": fragments,
        "model_calls": model_calls,
        "vision_requests": [],
        "config": {
            "ocr_default_profile": settings.ocr_profile,
            "layout_default_profile": "medical_inpatient_zh",
            "llm_default_profile": model_profiles_payload()["active_profile_id"],
            "vision_fallback_enabled": True,
            "vision_fallback_requires_manual_approval": True,
            "gold_sample_target_min": 30,
        },
    }


def quality_summary(case: CaseRecord) -> dict:
    document = json.loads(case.document_ir_json) if case.document_ir_json else {"blocks": []}
    diagnostics_payload = json_loads(case.diagnostics_json, {})
    blocks = document.get("blocks", [])
    metadata = document.get("metadata", {})
    avg = sum(float(block.get("confidence", 0) or 0) for block in blocks) / len(blocks) if blocks else 0
    low = len([block for block in blocks if float(block.get("confidence", 0) or 0) < 0.75])
    unavailable = metadata.get("ocr_unavailable_engines") or _extract_unavailable_ocr_engines(diagnostics_payload)
    attempted = metadata.get("ocr_attempted_engines") or _extract_attempted_ocr_engines(diagnostics_payload)
    unavailable_reasons = metadata.get("ocr_unavailable_reasons") or _extract_unavailable_ocr_reasons(diagnostics_payload)
    return {
        "page_count": len({block.get("page", 1) for block in blocks}) if blocks else 0,
        "ocr_block_count": len(blocks),
        "fragment_count": len(blocks),
        "avg_ocr_confidence": avg,
        "low_confidence_block_count": low,
        "quality_band": "good" if avg >= 0.9 else "fair" if avg >= 0.75 else "poor",
        "needs_vision_fallback": avg < 0.75,
        "input_kind": metadata.get("input_kind"),
        "ocr_adapter": metadata.get("ocr_adapter", "intelligent_document"),
        "ocr_engine": metadata.get("ocr_engine", "none"),
        "ocr_profile": metadata.get("ocr_profile") or settings.ocr_profile,
        "ocr_accelerator": metadata.get("accelerator"),
        "ocr_intelligent_status": metadata.get("ocr_intelligent_status") or ("failed" if case.status == "failed" else None),
        "ocr_attempted_engines": attempted,
        "ocr_unavailable_engines": unavailable,
        "ocr_unavailable_reasons": unavailable_reasons,
        "ocr_engine_errors": metadata.get("ocr_engine_errors") or _extract_ocr_engine_errors(diagnostics_payload),
        "ocr_page_quality": metadata.get("ocr_page_quality", []),
    }


def processing_run(case: CaseRecord) -> dict:
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
            "rule_ms": 0,
            "llm_call_count": len(usage),
            "layout_provider": quality.get("ocr_engine") or "intelligent_document",
            "ocr_adapter": quality.get("ocr_adapter") or "intelligent_document",
            "ocr_engine": quality.get("ocr_engine") or "none",
            "ocr_intelligent_status": quality.get("ocr_intelligent_status") or "",
            "ocr_attempted_engine_count": len(quality.get("ocr_attempted_engines") or []),
            "ocr_unavailable_engine_count": len(quality.get("ocr_unavailable_engines") or []),
            "ocr_unavailable_reasons": quality.get("ocr_unavailable_reasons") or {},
            "page_cache_hit_count": len([item for item in page_quality if item.get("cache_status") == "hit"]),
            "low_quality_page_count": len([item for item in page_quality if item.get("quality_band") == "poor"]),
            "llm_skipped_no_evidence_count": len([result for result in results if result.error_code == "NO_EVIDENCE_CANDIDATES_SKIPPED_LLM"]),
            "llm_cache_hit_count": len([item for item in usage if item.get("usage", {}).get("llm_cache_status") == "hit"]),
        },
        "error_message": diagnostics_payload.get("error"),
        "created_at": case.created_at.isoformat(),
        "completed_at": case.updated_at.isoformat() if case.status in {"completed", "failed"} else None,
    }


def frontend_evidence_config() -> dict:
    return {
        "basic_field_labels": ["姓名", "性别", "年龄", "住址", "民族", "婚姻", "职业", "住院号", "科室", "入院时间", "出院时间"],
        "section_labels": ["主诉", "现病史", "既往史", "个人史", "家族史", "体格检查", "辅助检查", "入院诊断", "出院诊断", "手术记录", "出院情况", "出院记录"],
        "inline_record_labels": ["主诉", "现病史", "既往史", "个人史", "家族史", "体格检查", "辅助检查", "诊断", "手术记录", "出院情况"],
        "section_tones": {
            "basic": ["基本", "首页", "信息", "姓名", "年龄", "性别"],
            "present": ["主诉", "现病", "入院"],
            "history": ["既往", "个人", "家族", "病史"],
            "diagnosis": ["诊断", "出院", "医嘱"],
            "exam": ["检验", "检查", "影像", "化验", "体格", "辅助"],
        },
        "document_title_patterns": ["病历", "病案", "入院记录", "出院记录", "病程记录", "手术记录", "首页"],
        "common_ocr_repairs": [],
    }


def _extract_unavailable_ocr_engines(diagnostics_payload: dict) -> list[str]:
    error = str(diagnostics_payload.get("error", ""))
    match = re.search(r"unavailable=([^;]+)", error)
    if not match:
        return []
    value = match.group(1).strip()
    return [] if value == "none" else [item.strip() for item in value.split(",") if item.strip()]


def _extract_attempted_ocr_engines(diagnostics_payload: dict) -> list[str]:
    error = str(diagnostics_payload.get("error", ""))
    match = re.search(r"attempted=([^;]+)", error)
    if not match:
        return []
    value = match.group(1).strip()
    return [] if value == "none" else [item.strip() for item in value.split(",") if item.strip()]


def _extract_unavailable_ocr_reasons(diagnostics_payload: dict) -> dict:
    error = str(diagnostics_payload.get("error", ""))
    match = re.search(r"reasons=([^;]+)", error)
    if not match:
        return {engine: _default_ocr_unavailable_reason(engine) for engine in _extract_unavailable_ocr_engines(diagnostics_payload)}
    value = match.group(1).strip()
    if value == "none":
        return {}
    reasons: dict[str, str] = {}
    for item in value.split("|"):
        name, separator, reason = item.strip().partition("=")
        if separator and name.strip() and reason.strip():
            reasons[name.strip()] = reason.strip()
    return reasons


def _default_ocr_unavailable_reason(engine: str) -> str:
    if engine == "document_ai_http":
        return "EYEX_OCR_DOCUMENT_AI_URL is not configured"
    if engine == "openai_document_vision":
        return "EYEX_OPENAI_API_KEY or OPENAI_API_KEY is not configured"
    if engine in {"paddleocr_vl", "paddle_structure_v3"}:
        return "Python package 'paddleocr' is not installed in the backend runtime"
    if engine == "docling":
        return "Python package 'docling' is not installed in the backend runtime"
    return "engine is unavailable"


def _extract_ocr_engine_errors(diagnostics_payload: dict) -> dict:
    error = diagnostics_payload.get("error")
    if not error:
        return {}
    match = re.search(r"errors=([^;]+)", str(error))
    if not match:
        return {"pipeline": error}
    value = match.group(1).strip()
    if value == "none":
        return {"pipeline": error}
    errors: dict[str, str] = {}
    for item in value.split("|"):
        name, separator, reason = item.strip().partition("=")
        if separator and name.strip() and reason.strip():
            errors[name.strip()] = reason.strip()
    return errors or {"pipeline": error}
