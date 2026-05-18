from __future__ import annotations

import re


NEGATION_TERMS = ("否认", "无", "未见", "未诉", "无明显", "无特殊")
UNCERTAIN_TERMS = ("?", "？", "待排", "疑似", "考虑", "可能")
SENTENCE_TERMINATORS = ("。", "；", ";", "\n")


def _negative_span(text: str, term: str, negation_terms: list[str]) -> str | None:
    negation_terms = [re.escape(term) for term in dict.fromkeys(negation_terms) if term]
    if not negation_terms:
        return None
    pattern = re.compile(rf"({'|'.join(negation_terms)})[^。；;\n]{{0,50}}{re.escape(term)}[^。；;\n]{{0,20}}")
    match = pattern.search(text)
    return _trim_span(match.group(0)) if match else None


def _positive_span(text: str, term: str) -> str | None:
    for match in re.finditer(re.escape(term), text):
        # Clip the span at sentence terminators on both sides so negations or
        # uncertainty markers that belong to a neighboring field in the next
        # clause cannot contaminate the positive evidence for this term.
        left_start = max(0, match.start() - 12)
        right_end = min(len(text), match.end() + 24)
        left_text = text[left_start:match.start()]
        for terminator in SENTENCE_TERMINATORS:
            idx = left_text.rfind(terminator)
            if idx != -1:
                left_start = left_start + idx + 1
                left_text = text[left_start:match.start()]
        right_text = text[match.end():right_end]
        for terminator in SENTENCE_TERMINATORS:
            idx = right_text.find(terminator)
            if idx != -1:
                right_end = match.end() + idx
                break
        # Negation that appears AFTER the term belongs to the next clause and
        # is handled by `_negative_span` against that clause's term. Only the
        # left context can negate the current occurrence.
        if any(negation in left_text for negation in NEGATION_TERMS):
            continue
        return _trim_span(text[left_start:right_end])
    return None


def _section_complete_negative_span(text: str) -> str | None:
    for pattern in (
        r"(?:既往史|个人史|系统回顾|病史)[：:]?\s*(?:无特殊|无明显异常|未见异常)",
        r"(?:余|其他)[^。；;\n]{0,12}(?:无特殊|无异常|未见异常)",
    ):
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return None


def _contains_uncertain(text: str) -> bool:
    return any(term in text for term in UNCERTAIN_TERMS)


def _trim_span(text: str) -> str:
    return text.strip(" ，,。；;\n\t")


def _match_group(match: re.Match, group: int | str) -> str | None:
    try:
        return match.group(group)
    except Exception:
        return None


def _normalize_rule_value(raw_value: str | None, rule) -> str | None:
    if raw_value is None:
        return rule.normalized_code
    if rule.code_map:
        return rule.code_map.get(raw_value, rule.code_map.get(raw_value.strip()))
    return rule.normalized_code or raw_value
