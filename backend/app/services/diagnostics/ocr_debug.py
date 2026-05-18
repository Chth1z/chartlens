from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher


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
