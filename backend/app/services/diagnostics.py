from __future__ import annotations

import json
import re
from collections import Counter
from difflib import SequenceMatcher

from app.core.config_loader import load_extraction_schema
from app.core.database import CaseRecord, ModelCallRecord, ProcessingRunRecord, VisionFallbackRequestRecord, json_loads
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


def _ocr_debug_summary(blocks: list[dict], metadata: dict) -> dict:
    checks = []
    checks.extend(_tile_boundary_checks(blocks, metadata))
    checks.extend(_fragmentation_checks(blocks))
    checks.extend(_duplicate_text_checks(blocks))
    checks.extend(_table_layout_checks(blocks))
    checks.extend(_low_quality_checks(metadata))
    candidate_metrics = metadata.get("ocr_candidate_metrics", [])
    if isinstance(candidate_metrics, list) and candidate_metrics:
        checks.append(
            {
                "code": "candidate_selection",
                "severity": "info",
                "phenomenon": "不同 DPI/预处理候选结果差异",
                "likely_reason": "低质扫描、表格或小字对渲染分辨率敏感",
                "action": "查看 ocr_candidate_metrics，保留字符覆盖和置信度更好的候选；不要盲目固定最高 DPI。",
                "evidence": {"candidates": candidate_metrics},
            }
        )
    return {
        "checks": checks,
        "recommended_profiles": _recommended_ocr_debug_profiles(checks),
        "candidate_metrics": candidate_metrics if isinstance(candidate_metrics, list) else [],
    }


def _tile_boundary_checks(blocks: list[dict], metadata: dict) -> list[dict]:
    tile_size = _safe_int(metadata.get("tile_max_side_len") or metadata.get("rapidocr_max_side_len"), default=0)
    if tile_size <= 0:
        return []
    hits = []
    for block in blocks:
        bbox = block.get("bbox") or []
        if len(bbox) != 4:
            continue
        x2 = float(bbox[2])
        remainder = x2 % tile_size
        if remainder <= 3 or abs(tile_size - remainder) <= 3:
            hits.append({"page": block.get("page", 1), "text": str(block.get("text", ""))[:40], "bbox": bbox})
    if not hits:
        return []
    return [
        {
            "code": "tile_boundary_crop_risk",
            "severity": "warning",
            "phenomenon": "crop/tile 图可能在右侧或边界处截断文本",
            "likely_reason": "tile 边界、坐标缩放或 padding 不足导致行框贴边",
            "action": "检查 debug crop；增加 tile_overlap/padding，或调整 bbox 坐标缩放。",
            "evidence": {"hit_count": len(hits), "examples": hits[:5]},
        }
    ]


def _fragmentation_checks(blocks: list[dict]) -> list[dict]:
    fragments = []
    ordered = sorted(blocks, key=lambda item: (int(item.get("page", 1) or 1), _bbox_mid_y(item), _bbox_x1(item)))
    for left, right in zip(ordered, ordered[1:]):
        if left.get("page", 1) != right.get("page", 1):
            continue
        if not _same_visual_line(left, right):
            continue
        left_text = str(left.get("text", "")).strip()
        right_text = str(right.get("text", "")).strip()
        if not left_text or not right_text or left_text == right_text:
            continue
        similarity = SequenceMatcher(None, left_text, right_text).ratio()
        if similarity >= 0.35:
            fragments.append(
                {
                    "page": left.get("page", 1),
                    "left": left_text[:40],
                    "right": right_text[:40],
                    "similarity": round(similarity, 3),
                }
            )
    if not fragments:
        return []
    return [
        {
            "code": "line_fragmentation_risk",
            "severity": "warning",
            "phenomenon": "OCR 原始行完整但重建后的文本破碎或同一行被切成多段",
            "likely_reason": "重叠窗口、tile 边界或行合并阈值不合适",
            "action": "调试行合并；按 y-overlap + 文本相似度合并，再做章节切分。",
            "evidence": {"fragment_count": len(fragments), "examples": fragments[:5]},
        }
    ]


def _duplicate_text_checks(blocks: list[dict]) -> list[dict]:
    texts = [_normalize_ocr_text(block.get("text", "")) for block in blocks]
    counts = Counter(text for text in texts if len(text) >= 4)
    duplicates = [{"text": text[:50], "count": count} for text, count in counts.items() if count > 1]
    if not duplicates:
        return []
    return [
        {
            "code": "duplicate_text_risk",
            "severity": "warning",
            "phenomenon": "同一句重复出现",
            "likely_reason": "重叠窗口或重复框未去重",
            "action": "用 bbox IoU + 文本相似度去重，保留置信度更高或覆盖更完整的候选。",
            "evidence": {"duplicate_count": len(duplicates), "examples": duplicates[:5]},
        }
    ]


def _table_layout_checks(blocks: list[dict]) -> list[dict]:
    row_counts: Counter[str] = Counter()
    for block in blocks:
        bbox = block.get("bbox") or []
        if len(bbox) != 4:
            continue
        text = str(block.get("text", "")).strip()
        if len(text) > 16:
            continue
        row_key = f"{block.get('page', 1)}:{round(_bbox_mid_y(block) / 12) * 12}"
        row_counts[row_key] += 1
    dense_rows = [row for row, count in row_counts.items() if count >= 3]
    if not dense_rows:
        return []
    return [
        {
            "code": "table_or_multicolumn_layout",
            "severity": "info",
            "phenomenon": "顶部信息和正文混在一起，或表格/多栏文本顺序混乱",
            "likely_reason": "表格、病案首页、多栏区域未先分区就按全页排序",
            "action": "先按版面分区；表格使用 cell-level 结构，正文使用标题锚点切分。",
            "evidence": {"dense_row_count": len(dense_rows), "examples": dense_rows[:5]},
        }
    ]


def _low_quality_checks(metadata: dict) -> list[dict]:
    page_quality = metadata.get("ocr_page_quality", [])
    poor_pages = [
        item
        for item in page_quality
        if isinstance(item, dict)
        and (item.get("quality_band") == "poor" or float(item.get("avg_confidence", 1) or 1) < 0.8)
    ]
    if not poor_pages:
        return []
    return [
        {
            "code": "low_quality_preprocess_needed",
            "severity": "warning",
            "phenomenon": "低质量图片、水印、摩尔纹、阴影或表格线干扰导致 OCR 覆盖不足",
            "likely_reason": "扫描/屏拍质量差，或水印/摩尔纹/阴影与文字纹理混淆",
            "action": "对该页评测 deshadow、screen_moire_soften、watermark_suppress、grayscale_autocontrast_sharpen 等预处理候选；不要默认覆盖原图结果。",
            "evidence": {"pages": poor_pages[:8]},
        }
    ]


def _recommended_ocr_debug_profiles(checks: list[dict]) -> list[str]:
    codes = {check.get("code") for check in checks}
    recommendations = []
    if {"tile_boundary_crop_risk", "line_fragmentation_risk"} & codes:
        recommendations.append("increase_tile_overlap_and_enable_debug_crops")
    if "low_quality_preprocess_needed" in codes:
        recommendations.extend(["deshadow_candidate", "screen_moire_soften_candidate", "watermark_suppress_candidate"])
    if "table_or_multicolumn_layout" in codes:
        recommendations.append("table_structure_cell_level")
    if "duplicate_text_risk" in codes:
        recommendations.append("bbox_iou_text_similarity_dedupe")
    return list(dict.fromkeys(recommendations))


def _safe_int(value, *, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _bbox_mid_y(block: dict) -> float:
    bbox = block.get("bbox") or [0, 0, 0, 0]
    return (float(bbox[1]) + float(bbox[3])) / 2 if len(bbox) == 4 else 0.0


def _bbox_x1(block: dict) -> float:
    bbox = block.get("bbox") or [0, 0, 0, 0]
    return float(bbox[0]) if len(bbox) == 4 else 0.0


def _same_visual_line(left: dict, right: dict) -> bool:
    left_bbox = left.get("bbox") or []
    right_bbox = right.get("bbox") or []
    if len(left_bbox) != 4 or len(right_bbox) != 4:
        return False
    top = max(float(left_bbox[1]), float(right_bbox[1]))
    bottom = min(float(left_bbox[3]), float(right_bbox[3]))
    overlap = max(0.0, bottom - top)
    min_height = max(1.0, min(float(left_bbox[3]) - float(left_bbox[1]), float(right_bbox[3]) - float(right_bbox[1])))
    return overlap / min_height >= 0.45


def _normalize_ocr_text(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip()


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
