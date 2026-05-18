from __future__ import annotations

import json

from app.core.settings import settings
from app.domain.models import DocumentIRBlock


OCR_DEBUG_METADATA_KEYS = (
    "ocr_candidate_metrics",
    "render_dpi_candidates",
    "render_dpi",
    "tile_max_side_len",
    "tile_overlap",
    "rapidocr_max_side_len",
    "image_preprocess",
    "image_preprocess_modes",
    "directml_safe_mode",
    "preprocess_profile",
    "merge_policy_version",
    "pipeline_stages",
    "stage_models",
    "stage_metrics",
)
OCR_DEBUG_LIST_METADATA_KEYS = {"ocr_candidate_metrics", "pipeline_stages", "stage_metrics"}


def _annotate_ocr_blocks(blocks: list[DocumentIRBlock], metadata: dict, source_page_kind: str) -> list[DocumentIRBlock]:
    engine = metadata.get("ocr_engine") or metadata.get("ocr_adapter") or "intelligent_document"
    model_name = metadata.get("model_name")
    model_version = metadata.get("model_version")
    accelerator = metadata.get("accelerator") or settings.ocr_accelerator
    engine_version = metadata.get("engine_version")
    route_profile_id = metadata.get("route_profile_id") or settings.ocr_profile
    annotated: list[DocumentIRBlock] = []
    for block in blocks:
        flags = list(block.quality_flags)
        if block.confidence < settings.ocr_intelligent_min_confidence and "low_confidence" not in flags:
            flags.append("low_confidence")
        annotated.append(
            block.model_copy(
                update={
                    "source_engine": str(engine),
                    "source_page_kind": source_page_kind,
                    "ocr_profile": settings.ocr_profile,
                    "layout_profile": "intelligent_document",
                    "quality_flags": flags,
                    "model_name": str(model_name) if model_name else block.model_name,
                    "model_version": str(model_version) if model_version else block.model_version,
                    "accelerator": str(accelerator) if accelerator else block.accelerator,
                    "engine_version": str(engine_version) if engine_version else block.engine_version,
                    "route_profile_id": str(route_profile_id) if route_profile_id else block.route_profile_id,
                }
            )
        )
    return annotated


def _page_quality_from_blocks(
    blocks: list[DocumentIRBlock],
    metadata: dict,
    *,
    default_page: int,
    cache_status: str,
) -> list[dict]:
    if not blocks:
        return [
            {
                "page": default_page,
                "kind": "image_pdf_ocr",
                "char_count": 0,
                "avg_confidence": 0.0,
                "quality_band": "poor",
                "cache_status": cache_status,
                "engine": metadata.get("ocr_engine", "none"),
                "failure_reason": metadata.get("ocr_intelligent_status", "no_engine_result"),
            }
        ]
    pages = sorted({block.page for block in blocks})
    quality = []
    for page in pages:
        page_blocks = [block for block in blocks if block.page == page]
        char_count = sum(len(block.text.strip()) for block in page_blocks)
        avg_confidence = sum(block.confidence for block in page_blocks) / len(page_blocks) if page_blocks else 0.0
        kind = page_blocks[0].source_page_kind or "image_pdf_ocr"
        quality.append(
            {
                "page": page,
                "kind": kind,
                "char_count": char_count,
                "avg_confidence": round(avg_confidence, 4),
                "quality_band": _quality_band(avg_confidence),
                "cache_status": cache_status,
                "engine": metadata.get("ocr_engine", "intelligent_document"),
            }
        )
    return quality


def _text_page_quality(page: int, text: str, kind: str) -> dict:
    confidence = 0.98 if text.strip() else 0.0
    return {
        "page": page,
        "kind": kind,
        "char_count": len(text.strip()),
        "avg_confidence": confidence,
        "quality_band": _quality_band(confidence),
        "cache_status": "not_applicable",
        "engine": "pdf_text" if kind == "native_pdf_text" else kind,
    }


def _quality_band(confidence: float) -> str:
    if confidence >= 0.9:
        return "good"
    if confidence >= 0.75:
        return "fair"
    return "poor"


def _merge_ocr_debug_metadata(metadata_items) -> dict:
    merged: dict = {}
    seen_by_key: dict[str, set[str]] = {}
    for metadata in metadata_items:
        if not isinstance(metadata, dict):
            continue
        for key in OCR_DEBUG_METADATA_KEYS:
            value = metadata.get(key)
            if value in (None, "", [], {}):
                continue
            if key in OCR_DEBUG_LIST_METADATA_KEYS:
                values = value if isinstance(value, list) else [value]
                target = merged.setdefault(key, [])
                seen = seen_by_key.setdefault(key, set())
                for item in values:
                    signature = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
                    if signature in seen:
                        continue
                    seen.add(signature)
                    target.append(item)
                continue
            if key not in merged:
                merged[key] = value
    return merged


def _ocr_unavailable_message(metadata: dict) -> str:
    unavailable = ", ".join(metadata.get("ocr_unavailable_engines", [])) or "none"
    attempted = ", ".join(metadata.get("ocr_attempted_engines", [])) or "none"
    status = metadata.get("ocr_intelligent_status", "no_engine_result")
    reasons = metadata.get("ocr_unavailable_reasons", {})
    errors = metadata.get("ocr_engine_errors", {})
    reason_text = " | ".join(f"{name}={reason}" for name, reason in reasons.items()) or "none"
    error_text = " | ".join(f"{name}={str(error).replace(';', ',')}" for name, error in errors.items()) or "none"
    return (
        "OCR_ENGINE_UNAVAILABLE: intelligent OCR produced no usable result; "
        f"status={status}; attempted={attempted}; unavailable={unavailable}; reasons={reason_text}; errors={error_text}"
    )
