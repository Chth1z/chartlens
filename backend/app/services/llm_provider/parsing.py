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
def _response_schema() -> dict[str, Any]:
    fact_schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "fact_type": {"type": "string"},
            "raw_text": {"type": "string"},
            "normalized": {"type": ["string", "null"]},
            "evidence_span": {"type": ["string", "null"]},
            "evidence_block_id": {"type": ["string", "null"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["fact_type", "raw_text", "normalized", "evidence_span", "evidence_block_id", "confidence"],
    }
    item_schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "field_key": {"type": "string"},
            "field_group_key": {"type": ["string", "null"]},
            "raw_value": {"type": ["string", "null"]},
            "normalized_code": {"type": ["string", "null"]},
            "status": {
                "type": "string",
                "enum": ["confirmed", "unknown", "not_mentioned", "conflict", "derived_candidate", "error"],
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence_text": {"type": ["string", "null"]},
            "evidence_span": {"type": ["string", "null"]},
            "evidence_block_id": {"type": ["string", "null"]},
            "evidence_type": {
                "type": ["string", "null"],
                "enum": [
                    "explicit_positive",
                    "explicit_negative",
                    "explicit_composite_negative",
                    "explicit_recorded_score",
                    "derived",
                    "inferred",
                    "no_evidence",
                    "conflict",
                    "event_fact",
                    None,
                ],
            },
            "page": {"type": ["integer", "null"], "minimum": 1},
            "bbox": {"type": "array", "items": {"type": "number"}},
            "facts": {"type": "array", "items": fact_schema},
            "reasoning_summary": {"type": ["string", "null"]},
            "review_required": {"type": "boolean"},
            "error_code": {"type": ["string", "null"]},
            "validator_messages": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "field_key",
            "field_group_key",
            "raw_value",
            "normalized_code",
            "status",
            "confidence",
            "evidence_text",
            "evidence_span",
            "evidence_block_id",
            "evidence_type",
            "page",
            "bbox",
            "facts",
            "reasoning_summary",
            "review_required",
            "error_code",
            "validator_messages",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"results": {"type": "array", "items": item_schema}},
        "required": ["results"],
    }


def _evidence_candidate_response_schema() -> dict[str, Any]:
    item_schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "field_key": {"type": "string"},
            "candidate_value": {"type": ["string", "null"]},
            "normalized_code": {
                "type": ["string", "null"],
                "description": (
                    "Actual extracted value, never a type-class placeholder. "
                    "When fields[].allowed_codes contains 'text' / 'integer' / 'float' / "
                    "'string' / 'number' / 'enum', that literal is a TYPE marker, not a "
                    "valid normalized_code. For free-text fields (e.g. hospital), set "
                    "normalized_code to the actual extracted string (e.g. '海安县中医院'). "
                    "For numeric fields, set normalized_code to the digit string (e.g. '72'). "
                    "If the document has no concrete value, return no candidate for this field."
                ),
            },
            "evidence_text": {
                "type": "string",
                "description": (
                    "Must be a contiguous, character-level substring of the cited block's "
                    "text field (the block whose block_id matches this candidate's block_id). "
                    "No paraphrasing, no reordering, no ellipsis, no synonym swap, no merging "
                    "across blocks. When a clause lists multiple items with 顿号 / 等 / 及 "
                    "(e.g. '否认高血压病、糖尿病、冠心病等病史'), quote the entire clause verbatim, "
                    "do not synthesize a per-item version such as '否认糖尿病'."
                ),
            },
            "field_label_seen": {"type": ["string", "null"]},
            "source_type": {"type": "string"},
            "document_region": {"type": ["string", "null"]},
            "visual_confirmed": {"type": "boolean"},
            "block_id": {"type": "string"},
            "block_ids": {"type": "array", "items": {"type": "string"}},
            "text": {"type": "string"},
            "page": {"type": "integer", "minimum": 1},
            "bbox": {"type": "array", "items": {"type": "number"}},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "ocr_confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "section_label": {"type": "string"},
            "document_kind": {"type": "string"},
            "forbidden_inference_flags": {"type": "array", "items": {"type": "string"}},
            "conflicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "block_id": {"type": ["string", "null"]},
                        "field_key": {"type": ["string", "null"]},
                        "normalized_code": {"type": ["string", "null"]},
                        "evidence_text": {"type": ["string", "null"]},
                        "reason": {"type": ["string", "null"]},
                    },
                    "required": ["block_id", "field_key", "normalized_code", "evidence_text", "reason"],
                },
            },
        },
        "required": [
            "field_key",
            "candidate_value",
            "normalized_code",
            "evidence_text",
            "field_label_seen",
            "source_type",
            "document_region",
            "visual_confirmed",
            "block_id",
            "block_ids",
            "text",
            "page",
            "bbox",
            "confidence",
            "ocr_confidence",
            "section_label",
            "document_kind",
            "forbidden_inference_flags",
            "conflicts",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"evidence_candidates": {"type": "array", "items": item_schema}},
        "required": ["evidence_candidates"],
    }


def _candidates_from_text(text: str) -> list[ExtractionCandidate]:
    parsed = _parse_llm_json_object(text)
    results = parsed.get("results") if isinstance(parsed, dict) else None
    if not isinstance(results, list):
        raise ValueError("LLM response must contain results array")
    return [ExtractionCandidate.model_validate(_normalize_candidate_payload(item)) for item in results if isinstance(item, dict)]


def _evidence_candidates_from_text(text: str) -> dict[str, list[EvidenceCandidate]]:
    parsed = _parse_llm_json_object(text)
    results = parsed.get("evidence_candidates") if isinstance(parsed, dict) else None
    if not isinstance(results, list):
        raise ValueError("LLM response must contain evidence_candidates array")
    grouped: dict[str, list[EvidenceCandidate]] = {}
    for item in results:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_evidence_candidate_payload(item)
        candidate = EvidenceCandidate.model_validate(normalized)
        if not candidate.field_key:
            continue
        grouped.setdefault(candidate.field_key, []).append(candidate)
    return grouped


def _parse_llm_json_object(text: str) -> dict[str, Any]:
    candidates = [text.strip()]
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        candidates.append(fenced.group(1).strip())
    extracted = _extract_first_json_object(text)
    if extracted:
        candidates.append(extracted)

    last_error: Exception | None = None
    for candidate in dict.fromkeys(item for item in candidates if item):
        try:
            parsed: Any = json.loads(candidate)
            if isinstance(parsed, str):
                parsed = json.loads(parsed)
            if isinstance(parsed, list):
                return {"results": parsed}
            if isinstance(parsed, dict):
                return parsed
        except Exception as exc:
            last_error = exc
    raise ValueError("LLM response must be a valid JSON object") from last_error


def _extract_first_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _normalize_evidence_candidate_payload(item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    evidence_text = normalized.get("evidence_text") or normalized.get("text") or ""
    normalized.setdefault("text", evidence_text)
    normalized.setdefault("block_id", (normalized.get("block_ids") or [""])[0])
    normalized.setdefault("block_ids", [normalized["block_id"]] if normalized.get("block_id") else [])
    normalized.setdefault("page", 1)
    normalized.setdefault("bbox", [])
    normalized.setdefault("confidence", normalized.get("score") or normalized.get("ocr_confidence") or 0.0)
    normalized.setdefault("ocr_confidence", normalized.get("confidence") or 0.0)
    normalized.setdefault("section_label", "未知")
    normalized.setdefault("document_kind", "unknown")
    normalized.setdefault("source_type", "ocr_text")
    normalized.setdefault("visual_confirmed", False)
    normalized.setdefault("forbidden_inference_flags", [])
    normalized.setdefault("conflicts", [])
    normalized.setdefault("block_ids", [])
    if not normalized.get("block_ids") and normalized.get("block_id"):
        normalized["block_ids"] = [normalized["block_id"]]
    return normalized


def _normalize_candidate_payload(item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    if normalized.get("status") == "no_evidence":
        normalized["status"] = "not_mentioned"
    if normalized.get("bbox") is None:
        normalized["bbox"] = []
    if normalized.get("facts") is None:
        normalized["facts"] = []
    if normalized.get("validator_messages") is None:
        normalized["validator_messages"] = []
    return normalized


def _anthropic_text(data: dict[str, Any]) -> str:
    parts = data.get("content", [])
    texts = [str(part.get("text", "")) for part in parts if isinstance(part, dict) and part.get("type") == "text"]
    text = "\n".join(item for item in texts if item).strip()
    if not text:
        raise ValueError("Anthropic response did not contain text content")
    return text


def _gemini_text(data: dict[str, Any]) -> str:
    candidates = data.get("candidates") or []
    if not candidates:
        raise ValueError("Gemini response did not contain candidates")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "\n".join(str(part.get("text", "")) for part in parts if isinstance(part, dict)).strip()
    if not text:
        raise ValueError("Gemini response did not contain text content")
    return text

