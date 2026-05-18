from __future__ import annotations

import re

from app.domain.models import DocumentIRBlock, LayoutNormalizationConfig

from app.services.layout_normalizer.sections import _compact_text


def _is_screen_chrome(text: str, config: LayoutNormalizationConfig) -> bool:
    compact = text.strip()
    if not compact:
        return False
    for pattern in config.screen_chrome_patterns:
        try:
            if re.search(pattern, compact):
                return True
        except re.error:
            continue
    return False


def _layout_sort_key(block: DocumentIRBlock) -> tuple[int, float, float, int, str]:
    if len(block.bbox) >= 4:
        return (block.page, float(block.bbox[1]), float(block.bbox[0]), block.reading_order, block.block_id)
    return (block.page, float(block.reading_order) * 10000.0, 0.0, block.reading_order, block.block_id)


def _same_line_groups(blocks: list[DocumentIRBlock], y_tolerance: float) -> list[list[DocumentIRBlock]]:
    groups: list[list[DocumentIRBlock]] = []
    current: list[DocumentIRBlock] = []
    current_page: int | None = None
    current_y: float | None = None
    for block in sorted(blocks, key=_layout_sort_key):
        if len(block.bbox) < 4:
            if current:
                groups.append(current)
                current = []
                current_page = None
                current_y = None
            groups.append([block])
            continue
        y = float(block.bbox[1])
        if current and current_page == block.page and current_y is not None and abs(y - current_y) <= y_tolerance:
            current.append(block)
            current_y = sum(float(item.bbox[1]) for item in current if len(item.bbox) >= 4) / max(1, len(current))
            continue
        if current:
            groups.append(current)
        current = [block]
        current_page = block.page
        current_y = y
    if current:
        groups.append(current)
    return groups


def _merge_same_line_blocks(
    blocks: list[DocumentIRBlock],
    config: LayoutNormalizationConfig,
) -> tuple[list[DocumentIRBlock], int]:
    merged: list[DocumentIRBlock] = []
    merge_count = 0
    for block in blocks:
        if merged and _can_merge_same_line(merged[-1], block, config):
            merged[-1] = _merge_blocks(merged[-1], block)
            merge_count += 1
            continue
        merged.append(block)
    return merged, merge_count


def _merge_wrapped_paragraph_blocks(
    blocks: list[DocumentIRBlock],
    config: LayoutNormalizationConfig,
) -> tuple[list[DocumentIRBlock], int]:
    merged: list[DocumentIRBlock] = []
    count = 0
    index = 0
    ordered = sorted(blocks, key=_layout_sort_key)
    while index < len(ordered):
        block = ordered[index]
        group = [block]
        cursor = index + 1
        while cursor < len(ordered) and _can_merge_wrapped_paragraph(group[-1], ordered[cursor], config):
            group.append(ordered[cursor])
            cursor += 1
        if len(group) > 1:
            merged.append(_merge_paragraph_group(group))
            count += len(group) - 1
            index = cursor
            continue
        merged.append(block)
        index += 1
    return merged, count


def _can_merge_wrapped_paragraph(left: DocumentIRBlock, right: DocumentIRBlock, config: LayoutNormalizationConfig) -> bool:
    if left.page != right.page or len(left.bbox) < 4 or len(right.bbox) < 4:
        return False
    if left.table_id or right.table_id or left.block_type == "cell" or right.block_type == "cell":
        return False
    if _starts_independent_field_label(left.text, config) or _starts_independent_field_label(right.text, config):
        return False
    if _is_screen_chrome(left.text, config) or _is_screen_chrome(right.text, config):
        return False
    if _looks_like_section_heading(left.text) or _looks_like_section_heading(right.text):
        return False
    left_x1, left_y1, left_x2, left_y2 = [float(value) for value in left.bbox[:4]]
    right_x1, right_y1, _, right_y2 = [float(value) for value in right.bbox[:4]]
    line_gap = right_y1 - left_y2
    if line_gap < -config.same_line_y_tolerance or line_gap > max(42.0, config.same_line_y_tolerance * 3):
        return False
    if abs(right_x1 - left_x1) > max(36.0, config.merge_horizontal_gap):
        return False
    left_text = left.text.strip()
    right_text = right.text.strip()
    if not left_text or not right_text:
        return False
    if re.search(r"[。；;!?！？]\s*$", left_text):
        return _is_short_continuation(right_text, right_y2 - right_y1)
    return True


def _looks_like_section_heading(text: str) -> bool:
    compact = _compact_text(text).strip()
    if not compact:
        return False
    return bool(re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9（）()·\-]{1,18}[:：]?", compact) and compact.endswith((":", "：")))


def _is_short_continuation(text: str, line_height: float) -> bool:
    del line_height
    return len(text) <= 32 and not re.search(r"[:：]\s*$", text)


def _merge_paragraph_group(blocks: list[DocumentIRBlock]) -> DocumentIRBlock:
    text = "".join(block.text.strip() for block in blocks)
    block_id = "+".join(block.block_id for block in blocks)
    bbox = _union_many([block.bbox for block in blocks])
    flags = [
        *(flag for block in blocks for flag in block.quality_flags),
        "layout_wrapped_paragraph",
    ]
    return blocks[0].model_copy(
        update={
            "block_id": block_id,
            "text": text,
            "bbox": bbox,
            "block_type": "paragraph",
            "confidence": min(block.confidence for block in blocks),
            "derived_from_block_ids": [block.block_id for block in blocks],
            "quality_flags": list(dict.fromkeys(flags)),
            "conflict_flags": list(dict.fromkeys(flag for block in blocks for flag in block.conflict_flags)),
        }
    )


def _can_merge_same_line(left: DocumentIRBlock, right: DocumentIRBlock, config: LayoutNormalizationConfig) -> bool:
    if left.page != right.page or len(left.bbox) < 4 or len(right.bbox) < 4:
        return False
    if left.table_id or right.table_id or left.block_type == "cell" or right.block_type == "cell":
        return False
    if abs(float(left.bbox[1]) - float(right.bbox[1])) > config.same_line_y_tolerance:
        return False
    if _starts_independent_field_label(right.text, config):
        return False
    if _horizontal_gap(left.bbox, right.bbox) > _allowed_merge_gap(left.text, config):
        return False
    return True


def _allowed_merge_gap(text: str, config: LayoutNormalizationConfig) -> float:
    if re.search(r"[:：]\s*$", text.strip()):
        return max(config.merge_horizontal_gap, 140.0)
    return config.merge_horizontal_gap


def _starts_independent_field_label(text: str, config: LayoutNormalizationConfig) -> bool:
    return _key_label_start(text, config.key_value_labels) is not None or _generic_field_label_start(text) is not None


def _key_label_start(text: str, labels: list[str]) -> str | None:
    compact = text.strip()
    for label in sorted((label for label in labels if label), key=len, reverse=True):
        if re.match(rf"^{re.escape(label)}\s*[:：]", compact):
            return label
    return None


def _generic_field_label_start(text: str) -> str | None:
    compact = re.sub(r"\s+", "", text.strip())
    match = re.match(r"^([\u4e00-\u9fffA-Za-z0-9（）()·\-]{1,12})[:：]", compact)
    if not match:
        return None
    return match.group(1)


def _horizontal_gap(left_bbox: list[float], right_bbox: list[float]) -> float:
    return float(right_bbox[0]) - float(left_bbox[2])


def _merge_blocks(left: DocumentIRBlock, right: DocumentIRBlock) -> DocumentIRBlock:
    text = f"{left.text.rstrip()} {right.text.lstrip()}".strip()
    block_id = f"{left.block_id}+{right.block_id}"
    bbox = _union_bbox(left.bbox, right.bbox)
    return left.model_copy(
        update={
            "block_id": block_id,
            "text": text,
            "bbox": bbox,
            "confidence": min(left.confidence, right.confidence),
            "quality_flags": list(dict.fromkeys([*left.quality_flags, *right.quality_flags, "layout_merged_line"])),
            "conflict_flags": list(dict.fromkeys([*left.conflict_flags, *right.conflict_flags])),
        }
    )


def _union_bbox(left: list[float], right: list[float]) -> list[float]:
    if len(left) < 4:
        return right
    if len(right) < 4:
        return left
    return [
        min(float(left[0]), float(right[0])),
        min(float(left[1]), float(right[1])),
        max(float(left[2]), float(right[2])),
        max(float(left[3]), float(right[3])),
    ]


def _union_many(boxes: list[list[float]]) -> list[float]:
    valid = [bbox for bbox in boxes if len(bbox) >= 4]
    if not valid:
        return []
    bbox = valid[0]
    for candidate in valid[1:]:
        bbox = _union_bbox(bbox, candidate)
    return bbox
