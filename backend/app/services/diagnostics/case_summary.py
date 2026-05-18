from __future__ import annotations

import json

from app.core.database import CaseRecord, json_loads
from app.core.settings import settings
from app.services.diagnostics.ocr_availability import (
    _extract_attempted_ocr_engines,
    _extract_ocr_engine_errors,
    _extract_unavailable_ocr_engines,
    _extract_unavailable_ocr_reasons,
)
from app.services.diagnostics.ocr_debug import _ocr_debug_summary
from app.services.diagnostics.processing_run import (
    _event_payload,
    _model_call_payload,
    _run_record_payload,
    _vision_request_payload,
    processing_run,
)
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
    run_records = sorted(case.processing_runs, key=lambda item: item.started_at)
    if run_records:
        runs = [_run_record_payload(run, case) for run in reversed(run_records)]
        latest_run = _run_record_payload(run_records[-1], case)
        events = [
            _event_payload(event)
            for run in reversed(run_records)
            for event in sorted(run.events, key=lambda item: item.started_at, reverse=True)
        ]
        model_calls = [
            _model_call_payload(call)
            for run in reversed(run_records)
            for call in sorted(run.model_calls, key=lambda item: item.created_at, reverse=True)
        ]
    else:
        latest_run = processing_run(case)
        runs = [latest_run] if latest_run else []
        events = []
        model_calls = _snapshot_model_calls(case, diagnostics_payload)
    return {
        "case_id": case.case_id,
        "quality": quality_summary(case),
        "latest_run": latest_run,
        "run_count": len(runs),
        "runs": runs,
        "events": events,
        "fragments": fragments,
        "model_calls": model_calls,
        "vision_requests": [
            _vision_request_payload(request)
            for request in sorted(case.vision_requests, key=lambda item: item.created_at, reverse=True)
        ],
        "config": {
            "ocr_default_profile": settings.ocr_profile,
            "layout_default_profile": "medical_inpatient_zh",
            "llm_default_profile": model_profiles_payload()["active_profile_id"],
            "vision_fallback_enabled": True,
            "vision_fallback_requires_manual_approval": True,
            "gold_sample_target_min": 30,
        },
    }


def _snapshot_model_calls(case: CaseRecord, diagnostics_payload: dict) -> list[dict]:
    return [
        {
            "call_id": f"call-{index}",
            "run_id": f"run-{case.case_id}",
            "provider": item.get("provider", "local_fallback"),
            "model": item.get("model") or item.get("provider", "local"),
            "mode": item.get("route", "local"),
            "stage": item.get("stage", "extract_document"),
            "field_keys": item.get("field_keys", []),
            "input_tokens": item.get("usage", {}).get("input_tokens", 0),
            "cached_input_tokens": item.get("usage", {}).get("cached_input_tokens", 0),
            "output_tokens": item.get("usage", {}).get("output_tokens", 0),
            "cost_usd": item.get("usage", {}).get("cost_usd", 0),
            "latency_ms": item.get("latency_ms", 0),
            "status": item.get("status", "completed"),
            "error_code": item.get("error_code"),
            "error_message": item.get("error_message"),
            "fallback_attempts": item.get("usage", {}).get("fallback_attempts", 0),
            "fallback_failures": item.get("usage", {}).get("fallback_failures", 0),
            "fallback_errors": item.get("usage", {}).get("fallback_errors", []),
            "llm_cache_status": item.get("usage", {}).get("llm_cache_status"),
            "llm_cache_key": item.get("usage", {}).get("llm_cache_key"),
            "created_at": case.updated_at.isoformat(),
        }
        for index, item in enumerate(diagnostics_payload.get("llm_usage", []), start=1)
    ]


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
    ocr_debug = _ocr_debug_summary(blocks, metadata)
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
        "ocr_trace": metadata.get("ocr_trace", {}),
        "ocr_debug": ocr_debug,
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
