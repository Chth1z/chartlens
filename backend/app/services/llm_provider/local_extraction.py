from __future__ import annotations
import json
import re
import base64
import hashlib
import mimetypes
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import httpx

from app.core.config_loader import load_document_profile, load_extraction_schema
from app.core.settings import settings
from app.domain.models import (
    DocumentIR, DocumentContext, DocumentIRBlock, EvidenceCandidate,
    ExtractedFact, ExtractionCandidate, FieldDecision, FieldDefinition,
    FieldGroup, RemoteExposurePolicy
)
from app.services.document_context import document_context_payload
from app.services.evidence import build_evidence_packs
from app.services.domain_profile import extraction_rules, extraction_system_prompt
from app.services.model_auth import api_keys_for_profile
from app.services.model_selection import get_active_model_profile, resolve_model_chain
from app.services.safe_errors import safe_error_message
from .types import SemanticExtractionProvider

class ConservativeLocalProvider(SemanticExtractionProvider):
    """Development-only provider: extracts only explicit evidence and never turns missing into negative."""

    name = "conservative-local-provider"
    route = "local_development"

    def extract_group(
        self,
        *,
        document_ir: DocumentIR,
        group: FieldGroup,
        fields: list[FieldDefinition],
        blocks: list[DocumentIRBlock],
    ) -> list[ExtractionCandidate]:
        del document_ir, group
        self.last_usage = {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0, "cost_usd": 0.0}
        return [_extract_explicit_field(field, blocks) for field in fields]


NEGATION_PREFIX = ("否认", "无", "未见", "不伴", "未发现", "未诉")
UNCERTAIN_TERMS = ("？", "疑似", "待排", "可能", "考虑")
FAMILY_TERMS = ("父", "母", "兄", "姐", "弟", "妹", "家族史")
COMPOSITE_LIFESTYLE_NEGATIVE = ("无烟酒不良嗜好", "无烟酒嗜好", "烟酒不沾", "无吸烟饮酒史", "不嗜烟酒")


def _extract_explicit_field(field: FieldDefinition, blocks: list[DocumentIRBlock]) -> ExtractionCandidate:
    if field.key in {"smoking_history", "drinking_history"}:
        composite = _first_text_match(blocks, COMPOSITE_LIFESTYLE_NEGATIVE, excluded_sections=field.excluded_sections)
        if composite:
            block, span = composite
            return _candidate(field, block, "无", "0", "explicit_composite_negative", span, 0.94, "组合表达明确否定烟酒")

    if field.extract_mode in {"fact_then_code", "computed_from_facts"}:
        return _extract_fact_then_code(field, blocks)

    negative = _first_negated_match(blocks, field.synonyms, field.negation_terms, excluded_sections=field.excluded_sections)
    positive = _first_positive_match(blocks, field.synonyms, field.negation_terms, excluded_sections=field.excluded_sections)
    uncertain = _first_uncertain_match(blocks, field.synonyms, excluded_sections=field.excluded_sections)

    if positive and negative:
        block, span = positive
        return _candidate(field, block, "冲突", "unknown", "conflict", span, 0.45, "肯定和否定线索冲突", status="conflict", review=True, error="CONFLICT")
    if uncertain:
        block, span = uncertain
        return _candidate(field, block, None, "unknown", "inferred", span, 0.5, "疑似或待排不能自动确认", status="derived_candidate", review=True, error="UNCERTAIN_EVIDENCE")
    if negative:
        block, span = negative
        return _candidate(field, block, "无", "0", "explicit_negative", span, 0.9, "原文明确否定")
    if positive:
        block, span = positive
        if _has_family_context(block.text, span):
            return _unknown(field, "NON_PATIENT_EXPERIENCER", "证据属于家族史或非患者本人")
        return _candidate(field, block, "有", "1", "explicit_positive", span, 0.9, "原文明确肯定")
    return _unknown(field, "NOT_MENTIONED", "未找到明确原文证据")


def _extract_fact_then_code(field: FieldDefinition, blocks: list[DocumentIRBlock]) -> ExtractionCandidate:
    if field.key in {"hh_grade", "wfns_grade", "fisher_grade", "mrs_score"}:
        score = _extract_recorded_score(field, blocks)
        if score:
            return score

    matches: list[tuple[DocumentIRBlock, str, str]] = []
    for block in blocks:
        if block.section_label in field.excluded_sections:
            continue
        for code, terms in field.code_map.items():
            for term in terms:
                if term in block.text:
                    matches.append((block, term, code))
    if not matches:
        return _unknown(field, "NOT_MENTIONED", "未找到明确原文证据")

    block, span, code = max(matches, key=lambda item: (item[0].confidence, len(item[1])))
    if field.key == "surgery_method" and any(non_def in block.text for non_def in ("脑室外引流", "腰大池引流", "气管切开")) and code == "unknown":
        return _unknown(field, "NO_DEFINITIVE_ANEURYSM_TREATMENT", "仅见非动脉瘤根治事件")
    fact = ExtractedFact(
        fact_type=field.key,
        raw_text=span,
        normalized=code,
        evidence_span=span,
        evidence_block_id=block.block_id,
        confidence=0.9,
    )
    return ExtractionCandidate(
        field_key=field.key,
        field_group_key=field.field_group_key,
        raw_value=span,
        normalized_code=code,
        status="confirmed",
        confidence=0.88,
        evidence_text=block.text,
        evidence_span=span,
        evidence_block_id=block.block_id,
        evidence_type="event_fact",
        page=block.page,
        bbox=block.bbox,
        facts=[fact],
        reasoning_summary="先抽事实再按配置编码",
        review_required=field.key in {"aneurysm_location", "surgery_method"},
    )


def _extract_recorded_score(field: FieldDefinition, blocks: list[DocumentIRBlock]) -> ExtractionCandidate | None:
    labels = {
        "hh_grade": r"(?:HH|Hunt[-\s]?Hess)\s*(?:分级|评分|级)?\s*[:：]?\s*([1-5ⅠⅡⅢⅣⅤ])",
        "wfns_grade": r"WFNS\s*(?:分级|评分|级)?\s*[:：]?\s*([1-5ⅠⅡⅢⅣⅤ])",
        "fisher_grade": r"Fisher\s*(?:分级|评分|级)?\s*[:：]?\s*([1-4ⅠⅡⅢⅣ])",
        "mrs_score": r"(?:mRS|MRS|改良Rankin)\s*(?:评分|分)?\s*[:：]?\s*([0-6])",
    }
    pattern_text = labels.get(field.key)
    if not pattern_text:
        return None
    pattern = re.compile(pattern_text, re.IGNORECASE)
    roman = {"Ⅰ": "1", "Ⅱ": "2", "Ⅲ": "3", "Ⅳ": "4", "Ⅴ": "5"}
    for block in blocks:
        match = pattern.search(block.text)
        if not match:
            continue
        code = roman.get(match.group(1), match.group(1))
        return _candidate(field, block, code, code, "explicit_recorded_score", match.group(0), 0.92, "原文明确记录评分")
    if field.key == "wfns_grade":
        gcs = _extract_gcs(blocks)
        if gcs:
            block, span, score = gcs
            derived = "1" if score == 15 else "2" if 13 <= score <= 14 else "4" if 7 <= score <= 12 else "5"
            return _candidate(field, block, derived, derived, "derived", span, 0.65, "由GCS推算，仅作候选", status="derived_candidate", review=True, error="DERIVED_REQUIRES_REVIEW")
    return None


def _extract_gcs(blocks: list[DocumentIRBlock]) -> tuple[DocumentIRBlock, str, int] | None:
    pattern = re.compile(r"GCS\s*[:：]?\s*(\d{1,2})")
    for block in blocks:
        match = pattern.search(block.text)
        if match:
            return block, match.group(0), int(match.group(1))
    return None


def _first_text_match(
    blocks: list[DocumentIRBlock],
    terms: list[str] | tuple[str, ...],
    *,
    excluded_sections: list[str],
) -> tuple[DocumentIRBlock, str] | None:
    for block in blocks:
        if block.section_label in excluded_sections:
            continue
        for term in terms:
            if term and term in block.text:
                return block, term
    return None


def _first_negated_match(
    blocks: list[DocumentIRBlock],
    positive_terms: list[str],
    negation_terms: list[str],
    *,
    excluded_sections: list[str],
) -> tuple[DocumentIRBlock, str] | None:
    prefixes = tuple(dict.fromkeys([*NEGATION_PREFIX, *negation_terms]))
    for block in blocks:
        if block.section_label in excluded_sections:
            continue
        for term in positive_terms:
            if not term:
                continue
            for prefix in prefixes:
                span = f"{prefix}{term}"
                if span in block.text:
                    return block, span
    return None


def _first_positive_match(
    blocks: list[DocumentIRBlock],
    positive_terms: list[str],
    negation_terms: list[str],
    *,
    excluded_sections: list[str],
) -> tuple[DocumentIRBlock, str] | None:
    prefixes = tuple(dict.fromkeys([*NEGATION_PREFIX, *negation_terms]))
    for block in blocks:
        if block.section_label in excluded_sections:
            continue
        for term in positive_terms:
            if not term:
                continue
            start = block.text.find(term)
            while start >= 0:
                before = block.text[max(0, start - 4) : start]
                if not any(before.endswith(prefix) for prefix in prefixes):
                    return block, term
                start = block.text.find(term, start + len(term))
    return None


def _first_uncertain_match(
    blocks: list[DocumentIRBlock],
    positive_terms: list[str],
    *,
    excluded_sections: list[str],
) -> tuple[DocumentIRBlock, str] | None:
    for block in blocks:
        if block.section_label in excluded_sections:
            continue
        for term in positive_terms:
            if term and term in block.text:
                start = max(0, block.text.find(term) - 8)
                end = min(len(block.text), block.text.find(term) + len(term) + 8)
                window = block.text[start:end]
                if any(marker in window for marker in UNCERTAIN_TERMS):
                    return block, window
    return None


def _has_family_context(text: str, span: str) -> bool:
    index = text.find(span)
    if index < 0:
        return False
    window = text[max(0, index - 20) : index + len(span) + 20]
    return any(term in window for term in FAMILY_TERMS)


def _candidate(
    field: FieldDefinition,
    block: DocumentIRBlock,
    raw_value: str | None,
    normalized_code: str,
    evidence_type: str,
    evidence_span: str,
    confidence: float,
    summary: str,
    *,
    status: str = "confirmed",
    review: bool | None = None,
    error: str | None = None,
) -> ExtractionCandidate:
    return ExtractionCandidate(
        field_key=field.key,
        field_group_key=field.field_group_key,
        raw_value=raw_value,
        normalized_code=normalized_code,
        status=status,
        confidence=confidence,
        evidence_text=block.text,
        evidence_span=evidence_span,
        evidence_block_id=block.block_id,
        evidence_type=evidence_type,
        page=block.page,
        bbox=block.bbox,
        reasoning_summary=summary,
        review_required=bool(review) if review is not None else confidence < 0.85,
        error_code=error,
    )


def _unknown(field: FieldDefinition, error_code: str, summary: str) -> ExtractionCandidate:
    return ExtractionCandidate(
        field_key=field.key,
        field_group_key=field.field_group_key,
        raw_value=None,
        normalized_code="unknown",
        status="not_mentioned",
        confidence=0.0,
        evidence_type="no_evidence",
        reasoning_summary=summary,
        review_required=True,
        error_code=error_code,
    )
