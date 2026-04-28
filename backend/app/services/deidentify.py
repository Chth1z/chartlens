from __future__ import annotations

import re

from pydantic import BaseModel


class DeidentificationResult(BaseModel):
    redacted_text: str
    replacements: dict[str, str]


PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("[身份证]", re.compile(r"\b\d{6}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b")),
    ("[电话]", re.compile(r"\b1[3-9]\d{9}\b")),
    ("[住院号]", re.compile(r"(?:住院号|住院编号|病案号|病历号)\s*[:：]?\s*([A-Za-z0-9-]{6,24})")),
    ("[地址]", re.compile(r"(?:地址|住址)\s*[:：]?\s*([^\n，。；;]{4,80})")),
    ("[姓名]", re.compile(r"(?:姓名|患者姓名)\s*[:：]?\s*([\u4e00-\u9fff]{2,4})")),
]


def deidentify_text(text: str) -> DeidentificationResult:
    redacted = text
    replacements: dict[str, str] = {}

    for label, pattern in PATTERNS:
        def replace(match: re.Match[str]) -> str:
            sensitive = match.group(1) if match.lastindex else match.group(0)
            replacements[sensitive] = label
            if match.lastindex:
                prefix = match.group(0).replace(sensitive, "")
                return f"{prefix}{label}"
            return label

        redacted = pattern.sub(replace, redacted)

    return DeidentificationResult(redacted_text=redacted, replacements=replacements)
