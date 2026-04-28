from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from statistics import median

from app.application.layout_analysis import LAYOUT_PARSER_VERSION
from app.domain.clinical import DocumentFragment, LayoutRegion, OcrBlock, OcrQualitySummary


DEFAULT_SECTION = "基本信息"
FRAGMENT_PARSER_VERSION = LAYOUT_PARSER_VERSION
DEFAULT_SECTION_ALIASES: dict[str, list[str]] = {
    "基本信息": ["基本信息", "病案首页", "住院病案首页", "入院记录"],
    "主诉": ["主诉"],
    "现病史": ["现病史", "病例摘要"],
    "既往史": ["既往史", "既往病史"],
    "个人史": ["个人史", "生活史"],
    "婚育史": ["婚育史", "月经史", "婚姻史"],
    "家族史": ["家族史"],
    "体格检查": ["体格检查", "查体", "专科检查"],
    "辅助检查": ["辅助检查", "实验室检查", "影像学检查"],
    "入院诊断": ["入院诊断", "初步诊断"],
    "出院诊断": ["出院诊断"],
    "手术记录": ["手术记录", "手术经过", "手术方式"],
    "出院情况": ["出院情况", "出院记录", "诊疗经过"],
}

FORM_FIELD_LABELS = [
    "病史陈述人",
    "可靠程度",
    "工作单位",
    "入院日期",
    "记录日期",
    "出院日期",
    "入院时间",
    "出院时间",
    "联系人",
    "姓名",
    "性别",
    "年龄",
    "住址",
    "民族",
    "婚姻",
    "职业",
]
_FORM_FIELD_PATTERN = re.compile(
    rf"(?=(?:{'|'.join(re.escape(label) for label in sorted(FORM_FIELD_LABELS, key=len, reverse=True))})\s*[:：])"
)
_FORM_FIELD_LABEL_PATTERN = re.compile(
    rf"(?:{'|'.join(re.escape(label) for label in sorted(FORM_FIELD_LABELS, key=len, reverse=True))})\s*[:：]"
)


@dataclass(frozen=True)
class FormFieldPiece:
    text: str
    start: int
    end: int


def build_document_fragments(
    blocks: Iterable[OcrBlock],
    *,
    source_kind: str = "ocr",
    section_aliases: dict[str, list[str]] | None = None,
    layout_regions: list[LayoutRegion] | None = None,
) -> list[DocumentFragment]:
    section_patterns = _section_patterns(section_aliases or DEFAULT_SECTION_ALIASES)
    current_section = DEFAULT_SECTION
    line_fragments: list[DocumentFragment] = []
    sorted_items = _sort_blocks_with_layout(blocks, layout_regions)

    for reading_order, (block, region) in enumerate(sorted_items, start=1):
        text = block.text.strip()
        if not text:
            continue
        detected = _detect_section(text, section_patterns)
        section_name, section_confidence = _classify_section(
            text,
            detected=detected,
            current_section=current_section,
            region=region,
            has_layout=bool(layout_regions),
        )
        if section_name != "unknown_section":
            current_section = section_name
        line_fragments.append(
            DocumentFragment(
                page=block.page,
                reading_order=reading_order,
                text=text,
                bbox=block.bbox,
                confidence=block.confidence,
                section_name=section_name,
                block_type="title" if detected and _is_title_only(text, detected) else "line",
                source_kind=source_kind if source_kind in {"pdf_text", "ocr", "pp_structure", "manual"} else "ocr",
                layout_region_id=region.region_id if region else None,
                layout_type=region.region_type if region else None,
                section_confidence=section_confidence,
                parser_version=FRAGMENT_PARSER_VERSION,
            )
        )
    form_field_fragments = _build_form_field_fragments(line_fragments)
    paragraph_fragments = _build_paragraph_fragments(line_fragments)
    return form_field_fragments + paragraph_fragments + line_fragments


def summarize_ocr_quality(
    blocks: Iterable[OcrBlock],
    fragments: Iterable[DocumentFragment],
    *,
    low_confidence_threshold: float | None = None,
) -> OcrQualitySummary:
    block_list = list(blocks)
    fragment_list = list(fragments)
    threshold = low_confidence_threshold if low_confidence_threshold is not None else 0.80
    summary_fragments = [fragment for fragment in fragment_list if fragment.block_type not in {"line", "form_field"}]
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


def _section_patterns(aliases: dict[str, list[str]]) -> dict[str, re.Pattern[str]]:
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


def _build_form_field_fragments(lines: list[DocumentFragment]) -> list[DocumentFragment]:
    fragments: list[DocumentFragment] = []
    for line_index, line in enumerate(lines):
        if line.page > 2 and line.section_name != "基本信息":
            continue
        for piece_index, piece in enumerate(_split_form_fields(line.text), start=1):
            text = piece.text
            bbox = _text_piece_bbox(line.bbox, piece.start, piece.end, len(line.text.strip()))
            label = _label_without_value(text)
            if label:
                adjacent = _adjacent_form_value(lines, line_index)
                if not adjacent:
                    continue
                value, value_bbox = adjacent
                text = f"{label}：{value}"
                bbox = _merge_bboxes([bbox, value_bbox])
            fragments.append(
                DocumentFragment(
                    page=line.page,
                    reading_order=line.reading_order * 100 + piece_index,
                    text=text,
                    bbox=bbox,
                    confidence=max(line.confidence, 0.90),
                    section_name="基本信息",
                    block_type="form_field",
                    source_kind=line.source_kind,
                    layout_region_id=line.layout_region_id,
                    layout_type=line.layout_type,
                    section_confidence=line.section_confidence,
                    parser_version=line.parser_version,
                )
            )
    return fragments


def _split_form_fields(text: str) -> list[FormFieldPiece]:
    stripped = text.strip()
    if not stripped:
        return []
    matches = list(_FORM_FIELD_LABEL_PATTERN.finditer(stripped))
    pieces: list[FormFieldPiece] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(stripped)
        raw_piece = stripped[start:end]
        left_trimmed = len(raw_piece) - len(raw_piece.lstrip(" ，,;；"))
        right_trimmed = len(raw_piece.rstrip(" ，,;；"))
        piece_text = raw_piece.strip(" ，,;；")
        if _starts_with_form_label(piece_text):
            pieces.append(FormFieldPiece(text=piece_text, start=start + left_trimmed, end=start + right_trimmed))
    return pieces


def _starts_with_form_label(text: str) -> bool:
    return any(re.match(rf"^{re.escape(label)}\s*[:：]", text) for label in FORM_FIELD_LABELS)


def _label_without_value(text: str) -> str | None:
    labels = "|".join(re.escape(label) for label in sorted(FORM_FIELD_LABELS, key=len, reverse=True))
    match = re.match(rf"^({labels})\s*[:：]\s*$", text.strip())
    return match.group(1) if match else None


def _adjacent_form_value(lines: list[DocumentFragment], label_index: int) -> tuple[str, list[float]] | None:
    label_line = lines[label_index]
    for candidate in lines[label_index + 1 : label_index + 4]:
        if candidate.page != label_line.page:
            break
        if not _same_row_right_neighbor(label_line, candidate):
            continue
        if _starts_with_form_label(candidate.text):
            return None
        value = _strip_following_form_labels(candidate.text)
        if value:
            return value, candidate.bbox
    return None


def _text_piece_bbox(bbox: list[float], start: int, end: int, text_length: int) -> list[float]:
    if len(bbox) < 4 or text_length <= 0:
        return bbox
    x1, y1, x2, y2 = bbox
    width = max(0.0, x2 - x1)
    if width <= 0:
        return bbox
    left = x1 + width * max(0.0, min(1.0, start / text_length))
    right = x1 + width * max(0.0, min(1.0, end / text_length))
    padding = min(8.0, width * 0.015)
    return [max(x1, left - padding), y1, min(x2, right + padding), y2]


def _same_row_right_neighbor(label_line: DocumentFragment, candidate: DocumentFragment) -> bool:
    if len(label_line.bbox) < 4 or len(candidate.bbox) < 4:
        return False
    label_x1, label_y1, label_x2, label_y2 = label_line.bbox
    value_x1, value_y1, _, value_y2 = candidate.bbox
    label_center = (label_y1 + label_y2) / 2
    value_center = (value_y1 + value_y2) / 2
    row_tolerance = max(_height(label_line.bbox), _height(candidate.bbox), 18.0) * 0.7
    x_gap = value_x1 - label_x2
    return abs(label_center - value_center) <= row_tolerance and 0 <= x_gap <= 240


def _strip_following_form_labels(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.strip())
    pieces = [piece.strip(" ，,;；") for piece in _FORM_FIELD_PATTERN.split(normalized)]
    return pieces[0] if pieces else normalized


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
    if previous.layout_region_id and current.layout_region_id and previous.layout_region_id != current.layout_region_id:
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
        layout_region_id=first.layout_region_id,
        layout_type=first.layout_type,
        section_confidence=round(sum(line.section_confidence for line in lines) / len(lines), 4),
        parser_version=first.parser_version,
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
    if stripped in {"辅助检查", "病例摘要", "初步诊断", "医师签名"}:
        return True
    return bool(re.match(r"^[\u4e00-\u9fffA-Za-z0-9（）()、.．]{2,12}[:：]\s*$", stripped))


def _is_title_only(text: str, section_name: str) -> bool:
    stripped = re.sub(r"^[\s一二三四五六七八九十0-9（）()、.．]+", "", text.strip())
    stripped = stripped.rstrip(":：")
    return stripped == section_name or len(stripped) <= len(section_name) + 1


def _block_sort_key(block: OcrBlock) -> tuple[int, float, float]:
    if len(block.bbox) >= 2:
        return (block.page, block.bbox[1], block.bbox[0])
    return (block.page, float("inf"), float("inf"))


def _sort_blocks_with_layout(
    blocks: Iterable[OcrBlock],
    layout_regions: list[LayoutRegion] | None,
) -> list[tuple[OcrBlock, LayoutRegion | None]]:
    regions_by_page: dict[int, list[LayoutRegion]] = {}
    for region in layout_regions or []:
        regions_by_page.setdefault(region.page, []).append(region)
    items = [(block, _region_for_block(block, regions_by_page.get(block.page, []))) for block in blocks]
    if not layout_regions:
        return sorted(items, key=lambda item: _block_sort_key(item[0]))
    return sorted(items, key=_layout_block_sort_key)


def _layout_block_sort_key(item: tuple[OcrBlock, LayoutRegion | None]) -> tuple[int, int, float, float]:
    block, region = item
    block_key = _block_sort_key(block)
    return (block.page, region.reading_order if region else 9999, block_key[1], block_key[2])


def _region_for_block(block: OcrBlock, regions: list[LayoutRegion]) -> LayoutRegion | None:
    if not regions:
        return None
    center_region = _region_containing_center(block, regions)
    if center_region is not None:
        return center_region
    scored = [(_iou(block.bbox, region.bbox), region) for region in regions]
    scored = [(score, region) for score, region in scored if score > 0]
    if not scored:
        return None
    return max(scored, key=lambda item: (item[0], item[1].score))[1]


def _region_containing_center(block: OcrBlock, regions: list[LayoutRegion]) -> LayoutRegion | None:
    if len(block.bbox) < 4:
        return None
    cx = (block.bbox[0] + block.bbox[2]) / 2
    cy = (block.bbox[1] + block.bbox[3]) / 2
    containing = [
        region
        for region in regions
        if len(region.bbox) >= 4 and region.bbox[0] <= cx <= region.bbox[2] and region.bbox[1] <= cy <= region.bbox[3]
    ]
    if not containing:
        return None
    return max(containing, key=lambda region: (region.score, -_area(region.bbox)))


def _iou(first: list[float], second: list[float]) -> float:
    if len(first) < 4 or len(second) < 4:
        return 0.0
    x1 = max(first[0], second[0])
    y1 = max(first[1], second[1])
    x2 = min(first[2], second[2])
    y2 = min(first[3], second[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if intersection == 0:
        return 0.0
    union = _area(first) + _area(second) - intersection
    return intersection / union if union > 0 else 0.0


def _area(bbox: list[float]) -> float:
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1]) if len(bbox) >= 4 else 0.0


def _classify_section(
    text: str,
    *,
    detected: str | None,
    current_section: str,
    region: LayoutRegion | None,
    has_layout: bool,
) -> tuple[str, float]:
    if detected:
        return detected, 0.96
    if not has_layout:
        return current_section, 0.60
    if region and region.score < 0.35:
        return "unknown_section", max(0.10, region.score)
    if region and region.region_type in {"table", "form"} and _looks_like_form_text(text):
        return "基本信息", max(0.70, region.score)
    if text.startswith(("主诉", "现病史", "既往史", "个人史", "婚姻史", "家族史", "辅助检查")):
        return current_section, 0.70
    if current_section != "unknown_section":
        return current_section, 0.58
    return "unknown_section", 0.35


def _looks_like_form_text(text: str) -> bool:
    return any(label in text for label in FORM_FIELD_LABELS)
