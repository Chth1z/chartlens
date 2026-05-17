"""Bounding box geometry utilities for OCR block processing.

Extracted from intelligent_ocr.py for reuse across preprocessing,
postprocessing, canonicalization, and engine modules.
"""

from __future__ import annotations

import unicodedata


def bbox_rect(bbox: list[float]) -> tuple[float, float, float, float] | None:
    if len(bbox) != 4:
        return None
    try:
        x1, y1, x2, y2 = [float(value) for value in bbox]
    except Exception:
        return None
    left, right = min(x1, x2), max(x1, x2)
    top, bottom = min(y1, y2), max(y1, y2)
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def bbox_iou(left: list[float], right: list[float]) -> float:
    if len(left) != 4 or len(right) != 4:
        return 0.0
    x1 = max(left[0], right[0])
    y1 = max(left[1], right[1])
    x2 = min(left[2], right[2])
    y2 = min(left[3], right[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if intersection <= 0:
        return 0.0
    left_area = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    right_area = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
    union = left_area + right_area - intersection
    return intersection / union if union > 0 else 0.0


def bbox_containment(outer: list[float], inner: list[float]) -> float:
    """Ratio of inner bbox area that is contained within outer bbox.

    Returns 1.0 if inner is fully contained, 0.0 if no overlap.
    Used by MinerU-style dedup to detect nested blocks where IoU
    may be low due to different sizes.
    """
    if len(outer) != 4 or len(inner) != 4:
        return 0.0
    ix1 = max(outer[0], inner[0])
    iy1 = max(outer[1], inner[1])
    ix2 = min(outer[2], inner[2])
    iy2 = min(outer[3], inner[3])
    intersection = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    inner_area = max(0.0, inner[2] - inner[0]) * max(0.0, inner[3] - inner[1])
    return intersection / inner_area if inner_area > 0 else 0.0


def overlap_length(left_start: float, left_end: float, right_start: float, right_end: float) -> float:
    return max(0.0, min(left_end, right_end) - max(left_start, right_start))



def merge_bboxes(bboxes: list[list[float]]) -> list[float]:
    rects = [bbox_rect(bbox) for bbox in bboxes]
    valid = [rect for rect in rects if rect is not None]
    if not valid:
        return []
    return [
        min(rect[0] for rect in valid),
        min(rect[1] for rect in valid),
        max(rect[2] for rect in valid),
        max(rect[3] for rect in valid),
    ]


def parse_bbox(value) -> list[float]:
    if isinstance(value, (list, tuple)) and len(value) == 4 and all(is_number(item) for item in value):
        return [float(item) for item in value]
    return parse_polygon(value)


def parse_polygon(value) -> list[float]:
    if not isinstance(value, (list, tuple)):
        to_list = getattr(value, "tolist", None)
        if callable(to_list):
            value = to_list()
    if not isinstance(value, (list, tuple)) or not value:
        return []
    points = value
    if all(is_number(item) for item in points) and len(points) >= 4:
        xs = [float(item) for index, item in enumerate(points) if index % 2 == 0]
        ys = [float(item) for index, item in enumerate(points) if index % 2 == 1]
        return [min(xs), min(ys), max(xs), max(ys)]
    try:
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
    except Exception:
        return []
    return [min(xs), min(ys), max(xs), max(ys)]


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def clean_text(text: str) -> str:
    import re
    return re.sub(r"\s+", " ", text).strip()


def comparable_ocr_line_signature(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return "".join(char for char in normalized if char.isalnum())


# --- Private aliases for backward compatibility with original module ---

_bbox_rect = bbox_rect
_bbox_iou = bbox_iou
_overlap_length = overlap_length
_merge_ocr_bboxes = merge_bboxes
_parse_bbox = parse_bbox
_parse_polygon = parse_polygon
_is_number = is_number
_clean_text = clean_text
_comparable_ocr_line_signature = comparable_ocr_line_signature
