from __future__ import annotations

from typing import Any


PREFERRED_SOURCE_STAGES = ("pp_structure_v3", "pp_ocr_v5", "paddleocr_vl", "document_ai_http")
SOURCE_OCR_ALLOWED_BLOCK_TYPES = {"line", "paragraph", "text", "title", "form_field", "key_value", "cell"}


def build_source_ocr_payload(raw_payload: dict[str, Any], document_payload: dict[str, Any]) -> dict[str, Any]:
    raw_payload = raw_payload if isinstance(raw_payload, dict) else {}
    document_payload = document_payload if isinstance(document_payload, dict) else {}

    raw_metadata = raw_payload.get("metadata") if isinstance(raw_payload.get("metadata"), dict) else {}
    source_blocks, source_name = _preferred_source_blocks(raw_payload, raw_metadata)
    if source_blocks:
        return {
            "blocks": source_blocks,
            "metadata": {
                **raw_metadata,
                "source": source_name,
            },
        }

    document_metadata = document_payload.get("metadata") if isinstance(document_payload.get("metadata"), dict) else {}
    return {
        "blocks": _sorted_source_blocks(_filter_source_blocks(document_payload.get("blocks"))),
        "metadata": {
            **document_metadata,
            "source": "document_ir",
        },
    }


def _preferred_source_blocks(raw_payload: dict[str, Any], raw_metadata: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    candidate_blocks = _blocks_from_candidate_sets(raw_metadata)
    if candidate_blocks:
        return candidate_blocks, "raw_candidate_sets"

    layout_blocks = _blocks_from_layout_regions(raw_metadata)
    if layout_blocks:
        return layout_blocks, "raw_layout_regions"

    raw_blocks = _sorted_source_blocks(_filter_source_blocks(raw_payload.get("blocks")))
    if raw_blocks:
        return raw_blocks, "raw_document_ir"

    return [], "document_ir"


def _blocks_from_candidate_sets(raw_metadata: dict[str, Any]) -> list[dict[str, Any]]:
    candidate_sets = raw_metadata.get("raw_candidates") or raw_metadata.get("candidate_sets")
    if not isinstance(candidate_sets, dict):
        return []

    for stage in PREFERRED_SOURCE_STAGES:
        stage_items = candidate_sets.get(stage)
        if not isinstance(stage_items, list):
            continue
        blocks = []
        for index, item in enumerate(stage_items, start=1):
            if not isinstance(item, dict):
                continue
            bbox = item.get("bbox") if isinstance(item.get("bbox"), list) else []
            if len(bbox) < 4:
                continue
            text = str(item.get("text") or "")
            if not _is_source_text_usable(text):
                continue
            block_type = str(item.get("block_type") or "line")
            if block_type not in SOURCE_OCR_ALLOWED_BLOCK_TYPES:
                continue
            blocks.append(
                {
                    "block_id": str(item.get("candidate_id") or item.get("layout_region_id") or f"{stage}-{index:04d}"),
                    "page": int(item.get("page") or 1),
                    "reading_order": index,
                    "text": text,
                    "bbox": bbox,
                    "confidence": float(item.get("confidence") or item.get("merge_confidence") or 0.0),
                    "block_type": block_type,
                    "source_engine": stage,
                    "layout_region_id": item.get("layout_region_id"),
                    "candidate_group_id": item.get("candidate_group_id"),
                    "canonical_source_ids": item.get("canonical_source_ids") if isinstance(item.get("canonical_source_ids"), list) else [],
                    "conflict_flags": item.get("conflict_flags") if isinstance(item.get("conflict_flags"), list) else [],
                    "merge_flags": item.get("merge_flags") if isinstance(item.get("merge_flags"), list) else [],
                }
            )
        if blocks:
            return _sorted_source_blocks(blocks)
    return []


def _blocks_from_layout_regions(raw_metadata: dict[str, Any]) -> list[dict[str, Any]]:
    layout_regions = raw_metadata.get("layout_regions")
    if not isinstance(layout_regions, list):
        return []
    blocks = []
    for index, item in enumerate(layout_regions, start=1):
        if not isinstance(item, dict):
            continue
        bbox = item.get("bbox") if isinstance(item.get("bbox"), list) else []
        if len(bbox) < 4:
            continue
        text = str(item.get("text") or "")
        if not _is_source_text_usable(text):
            continue
        block_type = str(item.get("block_type") or "line")
        if block_type not in SOURCE_OCR_ALLOWED_BLOCK_TYPES:
            continue
        blocks.append(
            {
                "block_id": str(item.get("layout_region_id") or item.get("candidate_group_id") or f"layout-{index:04d}"),
                "page": int(item.get("page") or 1),
                "reading_order": index,
                "text": text,
                "bbox": bbox,
                "confidence": float(item.get("confidence") or item.get("merge_confidence") or 0.0),
                "block_type": block_type,
                "source_engine": str(item.get("stage_source") or ""),
                "layout_region_id": item.get("layout_region_id"),
                "candidate_group_id": item.get("candidate_group_id"),
                "canonical_source_ids": item.get("canonical_source_ids") if isinstance(item.get("canonical_source_ids"), list) else [],
                "conflict_flags": item.get("conflict_flags") if isinstance(item.get("conflict_flags"), list) else [],
                "merge_flags": item.get("merge_flags") if isinstance(item.get("merge_flags"), list) else [],
            }
        )
    return _sorted_source_blocks(blocks)


def _filter_source_blocks(blocks: Any) -> list[dict[str, Any]]:
    if not isinstance(blocks, list):
        return []
    filtered: list[dict[str, Any]] = []
    for index, item in enumerate(blocks, start=1):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "")
        if not _is_source_text_usable(text):
            continue
        block = dict(item)
        block["block_id"] = str(item.get("block_id") or f"block-{index:04d}")
        block["page"] = int(item.get("page") or 1)
        block["reading_order"] = int(item.get("reading_order") or index)
        filtered.append(block)
    return filtered


def _sorted_source_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(item: dict[str, Any]) -> tuple[float, float, float, int]:
        bbox = item.get("bbox") if isinstance(item.get("bbox"), list) else []
        if len(bbox) >= 4:
            x1 = _safe_float(bbox[0])
            y1 = _safe_float(bbox[1])
        else:
            x1 = 0.0
            y1 = 0.0
        return (
            _safe_float(item.get("page") or 1),
            y1,
            x1,
            int(item.get("reading_order") or 0),
        )

    ordered = sorted(blocks, key=key)
    for index, block in enumerate(ordered, start=1):
        block["reading_order"] = index
    return ordered


def _is_source_text_usable(text: str) -> bool:
    normalized = text.strip()
    if not normalized:
        return False
    if _is_internal_ocr_metadata_text(normalized):
        return False
    if _is_likely_page_marker_text(normalized):
        return False
    return True


def _is_internal_ocr_metadata_text(text: str) -> bool:
    normalized = text.strip()
    return (
        normalized.lower() == "canonical_selected"
        or normalized.lower().startswith("canonical:")
        or normalized.lower().startswith("candidate_id")
        or normalized.lower().startswith("candidate_group_id")
        or normalized.lower().startswith("merge_flags")
        or normalized.lower().startswith("conflict_flags")
        or normalized.lower().startswith("layout_region_id")
        or normalized.lower().startswith("line_group_id")
        or any(normalized.lower().startswith(f"{stage}:") for stage in PREFERRED_SOURCE_STAGES)
    )


def _is_likely_page_marker_text(text: str) -> bool:
    normalized = text.strip()
    return bool(normalized) and normalized.startswith("第") and normalized.endswith("页")


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0
