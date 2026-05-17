"""OCR payload parsing — JSON, Markdown, PaddleX, RapidOCR output normalization."""

from __future__ import annotations

import json
import re
from typing import Any

from app.services.ocr_engine.types import IntelligentOcrBlock, IntelligentOcrResult
from app.services.ocr_engine.bbox_utils import (
    parse_bbox, parse_polygon, is_number, clean_text,
)

MARKDOWN_LINE = re.compile(r"^\s{0,3}(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)?(?P<text>.+?)\s*$")


def result_from_payload(engine: str, payload, *, default_confidence: float) -> IntelligentOcrResult:
    raw_blocks = list(_iter_payload_blocks(_payload_to_builtin(payload), default_confidence=default_confidence))
    return IntelligentOcrResult(engine=engine, blocks=raw_blocks, metadata={"ocr_raw_block_count": len(raw_blocks)})


def blocks_from_markdown(markdown: str, *, confidence: float = 0.8, page: int = 1) -> list[IntelligentOcrBlock]:
    blocks: list[IntelligentOcrBlock] = []
    for line in markdown.splitlines():
        match = MARKDOWN_LINE.match(line)
        if not match: continue
        text = match.group("text").strip()
        if not text or set(text) <= {"-", "|", " "}: continue
        bt = "table" if "|" in text else "text"
        blocks.append(IntelligentOcrBlock(page=page, text=text, confidence=confidence, block_type=bt))
    return blocks


def blocks_from_rapidocr_output(output, *, page: int = 1) -> list[IntelligentOcrBlock]:
    payload = output[0] if isinstance(output, tuple) and len(output) >= 1 else output
    if isinstance(payload, list):
        blocks = []
        for item in payload:
            try:
                points, text, score = item
            except Exception: continue
            if not str(text).strip(): continue
            blocks.append(IntelligentOcrBlock(page=page, text=str(text).strip(),
                bbox=parse_polygon(points), confidence=_bounded_float(score, default=0.0), block_type="text"))
        return blocks

    raw_texts = getattr(payload, "txts", None)
    if raw_texts is None:
        raw_texts = getattr(payload, "rec_texts", None)
    texts = _as_list(raw_texts)
    if not texts: return []
    boxes = _as_list(_first_present_attr(payload, "boxes", "dt_boxes"))
    scores = _as_list(_first_present_attr(payload, "scores", "rec_scores"))

    blocks = []
    for index, text in enumerate(texts):
        cleaned = clean_text(str(text))
        if not cleaned: continue
        points = boxes[index] if index < len(boxes) else []
        score = scores[index] if index < len(scores) else 0.0
        blocks.append(IntelligentOcrBlock(page=page, text=cleaned,
            bbox=parse_polygon(points), confidence=_bounded_float(score, default=0.0), block_type="text"))
    return blocks


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _payload_to_builtin(value):
    if isinstance(value, (str, int, float, bool)) or value is None: return value
    if isinstance(value, dict):
        return {str(k): _payload_to_builtin(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_payload_to_builtin(v) for v in value]
    for method_name in ("to_dict", "json", "to_json", "export"):
        method = getattr(value, method_name, None)
        if callable(method):
            try: return _payload_to_builtin(method())
            except Exception: pass
    if hasattr(value, "__dict__"):
        return _payload_to_builtin(vars(value))
    return str(value)


def _iter_payload_blocks(payload, *, default_confidence: float):
    if isinstance(payload, str):
        yield from blocks_from_markdown(payload, confidence=default_confidence)
        return
    if isinstance(payload, list):
        for item in payload:
            yield from _iter_payload_blocks(item, default_confidence=default_confidence)
        return
    if not isinstance(payload, dict): return

    if "blocks" in payload:
        blocks = payload.get("blocks")
        if isinstance(blocks, list):
            for item in blocks:
                yield from _iter_payload_blocks(item, default_confidence=default_confidence)
        return

    overall = payload.get("overall_ocr_res")
    if isinstance(overall, dict):
        page = _extract_int(payload, ("page", "page_id", "page_index", "page_num"), default=1)
        yield from _blocks_from_rec_text_payload(overall, page=max(1, page), default_confidence=default_confidence)
        return

    if isinstance(payload.get("rec_texts"), list):
        page = _extract_int(payload, ("page", "page_id", "page_index", "page_num"), default=1)
        yield from _blocks_from_rec_text_payload(payload, page=max(1, page), default_confidence=default_confidence)
        return

    text = _extract_text(payload)
    if text:
        page = max(1, _extract_int(payload, ("page", "page_id", "page_index", "page_num"), default=1))
        yield IntelligentOcrBlock(
            page=page, text=text, bbox=_extract_bbox(payload),
            confidence=_extract_confidence(payload, default_confidence),
            block_type=_extract_block_type(payload),
            table_id=_extract_optional_str(payload, ("table_id", "tableId")),
            row=_extract_optional_int(payload, ("row", "row_index", "row_id")),
            col=_extract_optional_int(payload, ("col", "column", "col_index", "column_index")),
            row_span=max(1, _extract_int(payload, ("row_span", "rowSpan", "rowspan"), default=1)),
            col_span=max(1, _extract_int(payload, ("col_span", "colSpan", "colspan"), default=1)),
            stage_source=_extract_optional_str(payload, ("stage_source", "stage")),
            candidate_id=_extract_optional_str(payload, ("candidate_id", "candidateId")),
            candidate_group_id=_extract_optional_str(payload, ("candidate_group_id", "candidateGroupId")),
            conflict_flags=_extract_string_list(payload.get("conflict_flags")),
            model_name=_extract_optional_str(payload, ("model_name", "modelName")),
            model_version=_extract_optional_str(payload, ("model_version", "modelVersion")),
            model_variant=_extract_optional_str(payload, ("model_variant", "modelVariant")),
            render_dpi=_extract_optional_int(payload, ("render_dpi", "renderDpi")),
            preprocess_profile=_extract_optional_str(payload, ("preprocess_profile", "preprocessProfile")),
        )
        return

    for value in payload.values():
        if isinstance(value, (list, dict)):
            yield from _iter_payload_blocks(value, default_confidence=default_confidence)


def _blocks_from_rec_text_payload(payload: dict, *, page: int, default_confidence: float):
    texts = payload.get("rec_texts")
    if not isinstance(texts, list): return
    scores = payload.get("rec_scores") if isinstance(payload.get("rec_scores"), list) else []
    polys = payload.get("rec_polys") if isinstance(payload.get("rec_polys"), list) else []
    boxes = payload.get("rec_boxes") if isinstance(payload.get("rec_boxes"), list) else []
    for index, raw_text in enumerate(texts):
        if not isinstance(raw_text, str): continue
        text = clean_text(raw_text)
        if not text: continue
        score = scores[index] if index < len(scores) and is_number(scores[index]) else default_confidence
        bbox_source = polys[index] if index < len(polys) else boxes[index] if index < len(boxes) else None
        yield IntelligentOcrBlock(page=page, text=text, bbox=parse_bbox(bbox_source),
            confidence=max(0.0, min(1.0, float(score))), block_type="text")


def _extract_text(payload: dict) -> str:
    for key in ("text", "rec_text", "content", "markdown", "md", "html"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return clean_text(value)
    return ""


def _extract_block_type(payload: dict) -> str:
    raw = str(payload.get("block_type") or payload.get("type") or payload.get("label") or "text").lower()
    if "table" in raw: return "table"
    if "cell" in raw: return "cell"
    if "title" in raw or "header" in raw: return "title"
    if "key" in raw and "value" in raw: return "key_value"
    if "form" in raw: return "form_field"
    return "text"


def _extract_bbox(payload: dict) -> list[float]:
    for key in ("bbox", "box", "coordinate", "rect"):
        value = payload.get(key)
        parsed = parse_bbox(value)
        if parsed: return parsed
    for key in ("poly", "polygon", "points"):
        value = payload.get(key)
        parsed = parse_polygon(value)
        if parsed: return parsed
    return []


def _extract_confidence(payload: dict, default: float) -> float:
    for key in ("confidence", "score", "rec_score", "prob"):
        value = payload.get(key)
        if is_number(value): return max(0.0, min(1.0, float(value)))
    return default


def _extract_int(payload: dict, keys: tuple, *, default: int) -> int:
    for key in keys:
        value = payload.get(key)
        if is_number(value): return int(value)
    return default


def _extract_optional_int(payload: dict, keys: tuple) -> int | None:
    for key in keys:
        value = payload.get(key)
        if is_number(value): return int(value)
    return None


def _extract_optional_str(payload: dict, keys: tuple) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip(): return str(value)
    return None


def _extract_string_list(value) -> list[str]:
    if not isinstance(value, list): return []
    return [str(item) for item in value if str(item).strip()]


def _bounded_float(value, *, default: float) -> float:
    try: parsed = float(value)
    except Exception: parsed = default
    return max(0.0, min(1.0, parsed))


def _first_present_attr(payload, *names):
    for name in names:
        value = getattr(payload, name, None)
        if value is not None:
            return value
    return None


def _as_list(value) -> list:
    if value is None: return []
    if isinstance(value, list): return value
    try: return list(value)
    except TypeError: return []


# Backward-compatible aliases
_result_from_payload = result_from_payload
_blocks_from_markdown = blocks_from_markdown
_blocks_from_rapidocr_output = blocks_from_rapidocr_output
_payload_to_builtin = _payload_to_builtin
