from __future__ import annotations

import re

from app.schemas.pipeline import OcrBlock


KEY_VALUE_LABELS = [
    "姓名",
    "性别",
    "年龄",
    "住址",
    "民族",
    "婚姻",
    "职业",
    "工作单位",
    "联系人",
    "病史陈述人",
    "可靠程度",
    "入院日期",
    "出院日期",
    "记录日期",
    "主诉",
    "现病史",
    "既往史",
    "个人史",
    "家族史",
    "入院诊断",
    "出院诊断",
    "出院情况",
    "手术记录",
    "手术经过",
    "手术方式",
]

_LABEL_PATTERN = re.compile(rf"(?<!^)(?=(?:{'|'.join(re.escape(label) for label in KEY_VALUE_LABELS)})\s*[:：])")


def postprocess_ocr_blocks(blocks: list[OcrBlock]) -> list[OcrBlock]:
    processed: list[OcrBlock] = []
    for block in blocks:
        pieces = _split_key_value_line(block.text)
        if len(pieces) <= 1:
            processed.append(block)
            continue
        for index, piece in enumerate(pieces):
            processed.append(
                OcrBlock(
                    page=block.page,
                    text=piece,
                    bbox=_segment_bbox(block.bbox, index, len(pieces)),
                    confidence=block.confidence,
                )
            )
    return processed


def _split_key_value_line(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text.strip())
    if not normalized:
        return []
    pieces = [piece.strip(" ，,;；") for piece in _LABEL_PATTERN.split(normalized)]
    return [piece for piece in pieces if piece]


def _segment_bbox(bbox: list[float], index: int, total: int) -> list[float]:
    if len(bbox) != 4 or total <= 1:
        return bbox
    x1, y1, x2, y2 = bbox
    width = (x2 - x1) / total
    return [x1 + width * index, y1, x1 + width * (index + 1), y2]
