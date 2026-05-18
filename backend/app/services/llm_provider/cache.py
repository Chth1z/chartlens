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
from .payloads import _field_evidence_pack_payload, _evidence_first_system_prompt, _document_profile_for_context, _document_profile_for_ir
from app.services.domain_profile import extraction_rules, extraction_system_prompt

PROMPT_VERSION = "eyex-evidence-pack-v4"
EVIDENCE_FIRST_PROMPT_VERSION = "eyex-evidence-first-v3"

def _llm_cache_key(
    profile,
    document_ir: DocumentIR,
    group: FieldGroup,
    fields: list[FieldDefinition],
    blocks: list[DocumentIRBlock],
) -> str:
    try:
        schema_version = load_extraction_schema().version
    except Exception:
        schema_version = "unknown"
    evidence_payload = _field_evidence_pack_payload(fields, blocks)
    document_profile = _document_profile_for_ir(document_ir)
    prompt_material = {
        "system": extraction_system_prompt(document_profile),
        "rules": extraction_rules(document_profile),
    }
    material = {
        "schema_version": schema_version,
        "prompt_version": PROMPT_VERSION,
        "document_profile_id": document_ir.profile_id,
        "domain_prompt_hash": hashlib.sha256(
            json.dumps(prompt_material, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "model_profile_id": getattr(profile, "profile_id", None),
        "model": getattr(profile, "model", None),
        "provider": getattr(profile, "provider", None),
        "group_key": group.key,
        "field_keys": [field.key for field in fields],
        "evidence_pack_hashes": {
            key: [item["pack_hash"] for item in packs]
            for key, packs in evidence_payload.items()
        },
    }
    return hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _evidence_first_cache_key(
    profile,
    document_context: DocumentContext,
    fields: list[FieldDefinition],
    *,
    stage: str,
) -> str:
    try:
        schema_version = load_extraction_schema().version
    except Exception:
        schema_version = "unknown"
    context_payload = document_context_payload(document_context, include_images=False)
    document_profile = _document_profile_for_context(document_context)
    prompt_material = {
        "system": _evidence_first_system_prompt(document_context),
        "rules": extraction_rules(document_profile),
    }
    material = {
        "schema_version": schema_version,
        "prompt_version": EVIDENCE_FIRST_PROMPT_VERSION,
        "stage": stage,
        "document_profile_id": document_context.profile_id,
        "document_context_hash": hashlib.sha256(
            json.dumps(context_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "domain_prompt_hash": hashlib.sha256(
            json.dumps(prompt_material, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "model_profile_id": getattr(profile, "profile_id", None),
        "model": getattr(profile, "model", None),
        "provider": getattr(profile, "provider", None),
        "field_keys": [field.key for field in fields],
        "field_policies": {field.key: field.evidence_policy.model_dump() for field in fields},
    }
    return hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _read_llm_result_cache(cache_key: str) -> list[ExtractionCandidate] | None:
    path = _llm_cache_path(cache_key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        results = data.get("results", [])
        if not isinstance(results, list):
            return None
        return [ExtractionCandidate.model_validate(item) for item in results if isinstance(item, dict)]
    except Exception:
        return None


def _read_evidence_candidate_cache(cache_key: str) -> dict[str, list[EvidenceCandidate]] | None:
    path = _llm_cache_path(cache_key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        payload = data.get("evidence_candidates_by_field", {})
        if not isinstance(payload, dict):
            return None
        return {
            str(field_key): [EvidenceCandidate.model_validate(item) for item in items if isinstance(item, dict)]
            for field_key, items in payload.items()
            if isinstance(items, list)
        }
    except Exception:
        return None


def _write_llm_result_cache(cache_key: str, results: list[ExtractionCandidate]) -> None:
    path = _llm_cache_path(cache_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "prompt_version": PROMPT_VERSION,
                "cache_key": cache_key,
                "results": [result.model_dump() for result in results],
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )


def _write_evidence_candidate_cache(cache_key: str, candidates_by_field: dict[str, list[EvidenceCandidate]]) -> None:
    path = _llm_cache_path(cache_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "prompt_version": EVIDENCE_FIRST_PROMPT_VERSION,
                "cache_key": cache_key,
                "evidence_candidates_by_field": {
                    field_key: [candidate.model_dump() for candidate in candidates]
                    for field_key, candidates in candidates_by_field.items()
                },
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )


def _llm_cache_path(cache_key: str) -> Path:
    return settings.storage_dir / "llm_cache" / f"{cache_key}.json"


def _cache_hit_usage(cache_key: str) -> dict[str, Any]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_input_tokens": 0,
        "cost_usd": 0.0,
        "llm_cache_status": "hit",
        "llm_cache_key": cache_key,
    }


def _cache_miss_usage(cache_key: str) -> dict[str, Any]:
    return {"llm_cache_status": "miss", "llm_cache_key": cache_key}

