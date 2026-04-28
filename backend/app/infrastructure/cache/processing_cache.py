from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.domain.clinical import DocumentFragment, EvidenceCandidate, FieldExtractionResult, OcrBlock
from app.domain.field_definitions import FieldDefinition
from app.domain.system_config import OcrProfileConfig

CACHE_VERSION = "v5"
LLM_CACHE_VERSION = "v1"


def cache_key(
    *,
    file_hash: str,
    ocr_profile_name: str,
    layout_profile_name: str,
    ocr_profile: OcrProfileConfig,
    fragment_parser_version: str = "legacy",
    layout_provider: str = "fallback_heuristic",
    layout_model: str = "heuristic",
    section_classifier_version: str = "clinical_section_v1",
) -> str:
    payload = {
        "version": CACHE_VERSION,
        "file_hash": file_hash,
        "ocr_profile": ocr_profile_name,
        "layout_profile": layout_profile_name,
        "fragment_parser_version": fragment_parser_version,
        "layout_provider": layout_provider,
        "layout_model": layout_model,
        "section_classifier_version": section_classifier_version,
        "pdf_dpi": ocr_profile.pdf_dpi,
        "preprocess": ocr_profile.preprocess.model_dump(),
        "engine_priority": ocr_profile.engine_priority,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return digest


def load_cached_processing(key: str) -> tuple[list[OcrBlock], list[DocumentFragment]] | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        blocks = [OcrBlock.model_validate(item) for item in payload.get("ocr_blocks", [])]
        fragments = [DocumentFragment.model_validate(item) for item in payload.get("fragments", [])]
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not blocks or not fragments:
        return None
    return blocks, fragments


def save_cached_processing(key: str, blocks: list[OcrBlock], fragments: list[DocumentFragment]) -> None:
    path = _cache_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    payload: dict[str, Any] = {
        "version": CACHE_VERSION,
        "ocr_blocks": [block.model_dump() for block in blocks],
        "fragments": [fragment.model_dump() for fragment in fragments],
    }
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(path)


def llm_cache_key(
    *,
    fields: list[FieldDefinition],
    evidence_by_field: dict[str, list[EvidenceCandidate]],
    field_dictionary_version: str,
    system_config_version: str,
    model: str,
    prompt_cache_key: str,
) -> str:
    evidence_payload = {
        key: [
            {
                "text": item.text,
                "page": item.page,
                "bbox": item.bbox,
                "ocr_confidence": item.ocr_confidence,
                "score": item.score,
            }
            for item in candidates
        ]
        for key, candidates in sorted(evidence_by_field.items())
    }
    payload = {
        "version": LLM_CACHE_VERSION,
        "field_keys": [field.key for field in fields],
        "field_dictionary_version": field_dictionary_version,
        "system_config_version": system_config_version,
        "model": model,
        "prompt_cache_key": prompt_cache_key,
        "evidence_hash": hashlib.sha256(
            json.dumps(evidence_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def load_cached_llm_results(key: str) -> list[FieldExtractionResult] | None:
    path = _llm_cache_path(key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version") != LLM_CACHE_VERSION:
            return None
        results = [FieldExtractionResult.model_validate(item) for item in payload.get("results", [])]
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return results or None


def save_cached_llm_results(key: str, results: list[FieldExtractionResult]) -> None:
    path = _llm_cache_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    payload = {
        "version": LLM_CACHE_VERSION,
        "results": [result.model_dump() for result in results],
    }
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(path)


def _cache_path(key: str) -> Path:
    return Path(settings.storage_dir) / "cache" / f"{key}.json"


def _llm_cache_path(key: str) -> Path:
    return Path(settings.storage_dir) / "cache" / "llm" / f"{key}.json"
