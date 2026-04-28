from __future__ import annotations

import re
from collections.abc import Iterable
from statistics import median

from app.schemas.pipeline import DocumentFragment, OcrBlock, OcrQualitySummary
from app.services.system_config import load_system_config


DEFAULT_SECTION = "基本信息"


def build_document_fragments(
    blocks: Iterable[OcrBlock],
    *,
    source_kind: str = "ocr",
) -> list[DocumentFragment]:
    section_patterns = _section_patterns()
    current_section = DEFAULT_SECTION
    line_fragments: list[DocumentFragment] = []

    for reading_order, block in enumerate(sorted(blocks, key=_block_sort_key), start=1):
        text = block.text.strip()
        if not text:
            continue
        detected = _detect_section(text, section_patterns)
        if detected:
            current_section = detected
        line_fragments.append(
            DocumentFragment(
                page=block.page,
                reading_order=reading_order,
                text=text,
                bbox=block.bbox,
                confidence=block.confidence,
                section_name=current_section,
                block_type="title" if detected and _is_title_only(text, detected) else "line",
                source_kind=source_kind if source_kind in {"pdf_text", "ocr", "pp_structure", "manual"} else "ocr",
            )
        )
    paragraph_fragments = _build_paragraph_fragments(line_fragments)
    return paragraph_fragments + line_fragments


def summarize_ocr_quality(
    blocks: Iterable[OcrBlock],
    fragments: Iterable[DocumentFragment],
    *,
    low_confidence_threshold: float | None = None,
) -> OcrQualitySummary:
    block_list = list(blocks)
    fragment_list = list(fragments)
    threshold = (
        low_confidence_threshold
        if low_confidence_threshold is not None
        else load_system_config().ocr.profile().low_confidence_threshold
    )
    summary_fragments = [fragment for fragment in fragment_list if fragment.block_type != "line"]
    page_count = len({block.page for block in block_list} | {fragment.page for fragment in summary_fragments})
    avg_confidence = (
        round(sum(block.confidence for block in block_list) / len(block_list), 4)
        if block_list
        else 0.0
    )
    low_count = sum(1 for block in block_list if block.confidence < threshold)
    low_ratio = low_count / len(block_list) if block_list else 1.0
    if avg_confidence >= 0.88 and low_ratio <= 0.15:
        band = "good"
    elif avg_confidence >= 0.65 and low_ratio <= 0.50:
        band = "fair"
    else:
        band = "poor"
    return OcrQualitySummary(
        page_count=page_count,
        ocr_block_count=len(block_list),
        fragment_count=len(summary_fragments),
        avg_ocr_confidence=avg_confidence,
        low_confidence_block_count=low_count,
        quality_band=band,
        needs_vision_fallback=band == "poor" or low_ratio > 0.35,
    )


def fragment_to_ocr_block(fragment: DocumentFragment) -> OcrBlock:
    return OcrBlock(
        page=fragment.page,
        text=fragment.text,
        bbox=fragment.bbox,
        confidence=fragment.confidence,
    )


def _section_patterns() -> dict[str, re.Pattern[str]]:
    aliases = load_system_config().layout.profile().section_aliases
    patterns: dict[str, re.Pattern[str]] = {}
    for section_name, values in aliases.items():
        candidates = list(dict.fromkeys([section_name, *values]))
        escaped = "|".join(re.escape(candidate) for candidate in candidates if candidate)
        if escaped:
            heading_prefix = r"(?:[一二三四五六七八九十]+[、.．]\s*|[（(]?[一二三四五六七八九十0-9]+[）)]\s*|[0-9]+[、.．]\s*)?"
            patterns[section_name] = re.compile(rf"^\s*{heading_prefix}(?:{escaped})\s*[:：]?", re.IGNORECASE)
    return patterns


def _detect_section(text: str, patterns: dict[str, re.Pattern[str]]) -> str | None:
    if text.startswith("病史陈述人"):
        return None
    for section_name, pattern in patterns.items():
        if pattern.search(text):
            return section_name
    return None


def _build_paragraph_fragments(lines: list[DocumentFragment]) -> list[DocumentFragment]:
    paragraphs: list[DocumentFragment] = []
    current: list[DocumentFragment] = []
    heights = [_height(line.bbox) for line in lines if _height(line.bbox) > 0]
    typical_height = median(heights) if heights else 20.0

    for line in lines:
        if not current:
            current = [line]
            continue
        previous = current[-1]
        if _should_merge(previous, line, typical_height):
            current.append(line)
        else:
            paragraphs.append(_merge_lines(current, len(paragraphs) + 1))
            current = [line]
    if current:
        paragraphs.append(_merge_lines(current, len(paragraphs) + 1))
    return paragraphs


def _should_merge(previous: DocumentFragment, current: DocumentFragment, typical_height: float) -> bool:
    if previous.page != current.page or previous.section_name != current.section_name:
        return False
    if current.block_type == "title":
        return False
    if _starts_new_local_heading(current.text):
        return False
    if previous.block_type == "title":
        return True
    if _ends_paragraph(previous.text):
        return False
    if previous.bbox and current.bbox and len(previous.bbox) >= 4 and len(current.bbox) >= 4:
        vertical_gap = current.bbox[1] - previous.bbox[3]
        if vertical_gap > max(typical_height * 1.8, 36):
            return False
    return True


def _merge_lines(lines: list[DocumentFragment], reading_order: int) -> DocumentFragment:
    first = lines[0]
    text = _join_wrapped_text([line.text for line in lines])
    return DocumentFragment(
        page=first.page,
        reading_order=reading_order,
        text=text,
        bbox=_merge_bboxes([line.bbox for line in lines]),
        confidence=round(sum(line.confidence for line in lines) / len(lines), 4),
        section_name=first.section_name,
        block_type="paragraph",
        source_kind=first.source_kind,
    )


def _join_wrapped_text(lines: list[str]) -> str:
    text = ""
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if not text:
            text = stripped
        elif text.endswith(("不", "未", "无", "具", "体")) or stripped.startswith(("详", "清", "明")):
            text += stripped
        elif text.endswith(("，", "、", "；", "：", ",", ";", ":")):
            text += stripped
        else:
            text += stripped
    return text


def _merge_bboxes(bboxes: list[list[float]]) -> list[float]:
    valid = [bbox for bbox in bboxes if len(bbox) >= 4]
    if not valid:
        return []
    return [min(b[0] for b in valid), min(b[1] for b in valid), max(b[2] for b in valid), max(b[3] for b in valid)]


def _height(bbox: list[float]) -> float:
    return max(0.0, bbox[3] - bbox[1]) if len(bbox) >= 4 else 0.0


def _ends_paragraph(text: str) -> bool:
    return text.rstrip().endswith(("。", "！", "？", ".", "!", "?"))


def _starts_new_local_heading(text: str) -> bool:
    stripped = text.strip()
    return bool(re.match(r"^[\u4e00-\u9fffA-Za-z0-9（）()、.．]{2,12}[:：]\s*$", stripped))


def _is_title_only(text: str, section_name: str) -> bool:
    stripped = re.sub(r"^[\s一二三四五六七八九十0-9（）()、.．]+", "", text.strip())
    stripped = stripped.rstrip(":：")
    return stripped == section_name or len(stripped) <= len(section_name) + 1


def _block_sort_key(block: OcrBlock) -> tuple[int, float, float]:
    if len(block.bbox) >= 2:
        return (block.page, block.bbox[1], block.bbox[0])
    return (block.page, float("inf"), float("inf"))
