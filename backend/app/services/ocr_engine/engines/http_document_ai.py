"""HTTP Document Intelligence engine + Remote PaddleOCR-VL engine."""
from __future__ import annotations

import base64
import json
import mimetypes
import re
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from app.core.settings import settings
from app.services.ocr_engine.types import IntelligentOcrBlock, IntelligentOcrResult
from app.services.ocr_engine.engine_base import DEFAULT_DOCUMENT_PROFILE_ID
from app.services.ocr_engine.payload_parse import (
    result_from_payload, blocks_from_markdown,
)
from app.services.ocr_engine.bbox_utils import clean_text

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
SIDECAR_API_CONTRACT_VERSION = "eyex-ocr-sidecar-v2"
SIDECAR_RESTART_MESSAGE = (
    "OCR sidecar is stale or incompatible; restart it with .\\stop.cmd, then .\\start.cmd so "
    "/health exposes api_contract_version=eyex-ocr-sidecar-v2."
)
KNOWN_PREFIX_FAILURE_PATTERNS = (
    "unable to avoid copy while creating an array as requested",
    "np.array(obj, copy=false)",
)


class HttpDocumentIntelligenceEngine:
    name = "document_ai_http"

    def __init__(self, endpoint=None, api_key=None, timeout_seconds=None,
                 client_factory=None, profile_id=DEFAULT_DOCUMENT_PROFILE_ID):
        self.endpoint = endpoint if endpoint is not None else settings.ocr_document_ai_url
        self.api_key = api_key if api_key is not None else settings.ocr_document_ai_api_key
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else settings.ocr_document_ai_timeout_seconds
        self.client_factory = client_factory
        self.profile_id = profile_id

    def available(self):
        return bool(self.endpoint)

    def unavailable_reason(self):
        return "EYEX_OCR_DOCUMENT_AI_URL is not configured"

    def extract(self, file_path: Path) -> IntelligentOcrResult:
        import httpx
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        if _is_paddlex_layout_parsing_endpoint(self.endpoint or ""):
            return self._extract_paddlex_layout_parsing(file_path, headers=headers)
        mime = _mime_type(file_path)
        factory = self.client_factory or (lambda: httpx.Client(timeout=self.timeout_seconds))
        with factory() as client:
            stale_result = _stale_sidecar_result(self.name, _sidecar_health_payload(client, self.endpoint or "", headers))
            if stale_result is not None:
                return stale_result
            with file_path.open("rb") as f:
                response = client.post(self.endpoint, headers=headers,
                    files={"file": (file_path.name, f, mime)}, data={"profile_id": self.profile_id})
        response.raise_for_status()
        payload = response.json()
        prefix_failure_result = _known_prefix_failure_result(self.name, payload)
        if prefix_failure_result is not None:
            return prefix_failure_result
        engine_name = payload.get("engine") if isinstance(payload, dict) and payload.get("engine") else self.name
        result = result_from_payload(str(engine_name), payload, default_confidence=0.9)
        return IntelligentOcrResult(engine=result.engine, blocks=result.blocks,
            metadata={**result.metadata, **_http_document_metadata(payload), "ocr_http_endpoint": self.endpoint})

    def _extract_paddlex_layout_parsing(self, file_path, *, headers):
        import httpx
        factory = self.client_factory or (lambda: httpx.Client(timeout=self.timeout_seconds))
        with factory() as client:
            response = client.post(self.endpoint, headers=headers,
                json={"file": base64.b64encode(file_path.read_bytes()).decode("ascii"),
                      "fileType": 0 if file_path.suffix.lower() == ".pdf" else 1})
        response.raise_for_status()
        payload = response.json()
        result = _result_from_paddlex_layout_payload(payload)
        return IntelligentOcrResult(engine=result.engine, blocks=result.blocks,
            metadata={**result.metadata, "ocr_http_endpoint": self.endpoint, "ocr_http_protocol": "paddlex_layout_parsing"})


class RemotePaddleOCRVLEngine(HttpDocumentIntelligenceEngine):
    name = "paddleocr_vl_remote"

    def __init__(self, endpoint=None, api_key=None, timeout_seconds=None,
                 client_factory=None, profile_id=DEFAULT_DOCUMENT_PROFILE_ID):
        remote = endpoint if endpoint is not None else settings.ocr_paddleocr_vl_url
        super().__init__(endpoint=remote or "",
            api_key=api_key if api_key is not None else settings.ocr_paddleocr_vl_api_key,
            timeout_seconds=timeout_seconds, client_factory=client_factory, profile_id=profile_id)

    def unavailable_reason(self):
        return "EYEX_OCR_PADDLEOCR_VL_URL is not configured for remote AMD/ROCm PaddleOCR-VL sidecar"


def _http_document_metadata(payload):
    if not isinstance(payload, dict): return {}
    metadata = {
        "ocr_http_attempted_engines": _string_list(payload.get("attempted_engines")),
        "ocr_http_unavailable_engines": _string_list(payload.get("unavailable_engines")),
        "ocr_http_unavailable_reasons": _string_dict(payload.get("unavailable_reasons")),
        "ocr_http_engine_errors": _string_dict(payload.get("engine_errors")),
    }
    nested = payload.get("metadata")
    if isinstance(nested, dict):
        from app.services.ocr_engine.payload_parse import _payload_to_builtin
        bn = _payload_to_builtin(nested)
        metadata["ocr_http_metadata"] = bn
        for k in ("pages", "tables", "cells", "raw_markdown", "stage_metrics", "candidate_sets",
                   "pipeline_stages", "render_dpi", "preprocess_profile", "merge_policy_version",
                   "ocr_trace",
                   "model_name", "model_version", "accelerator", "engine_version", "route_profile_id"):
            if k in bn: metadata[k] = bn[k]
    return metadata


def _sidecar_health_payload(client, endpoint: str, headers: dict[str, str]) -> dict | None:
    health_endpoint = _sidecar_health_endpoint(endpoint)
    if not health_endpoint:
        return None
    get = getattr(client, "get", None)
    if not callable(get):
        return None
    try:
        response = get(health_endpoint, headers=headers)
        if isinstance(response, dict):
            return response
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _sidecar_health_endpoint(endpoint: str) -> str:
    try:
        parsed = urlparse(endpoint)
    except Exception:
        return ""
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        return ""
    if parsed.path.rstrip("/").lower() != "/extract":
        return ""
    return f"{parsed.scheme or 'http'}://{parsed.netloc}/health"


def _stale_sidecar_result(engine_name: str, health_payload: dict | None) -> IntelligentOcrResult | None:
    if not isinstance(health_payload, dict):
        return None
    if health_payload.get("api_contract_version") == SIDECAR_API_CONTRACT_VERSION:
        return None
    return _restart_required_result(
        engine_name,
        "sidecar_contract",
        SIDECAR_RESTART_MESSAGE,
        health_payload=health_payload,
    )


def _known_prefix_failure_result(engine_name: str, payload) -> IntelligentOcrResult | None:
    if not isinstance(payload, dict):
        return None
    errors = _string_dict(payload.get("engine_errors"))
    joined = "\n".join(errors.values()).lower()
    if not any(pattern in joined for pattern in KNOWN_PREFIX_FAILURE_PATTERNS):
        return None
    return _restart_required_result(
        engine_name,
        "sidecar_stale_response",
        "OCR sidecar returned a known pre-fix NumPy parsing failure; restart the sidecar with .\\start.cmd so it loads the current OCR parser.",
        sidecar_errors=errors,
    )


def _restart_required_result(
    engine_name: str,
    error_key: str,
    message: str,
    *,
    health_payload: dict | None = None,
    sidecar_errors: dict[str, str] | None = None,
) -> IntelligentOcrResult:
    metadata = {
        "ocr_raw_block_count": 0,
        "ocr_http_engine_errors": {error_key: message},
        "ocr_http_restart_required": True,
        "ocr_http_restart_message": message,
    }
    if health_payload is not None:
        metadata["ocr_http_health"] = health_payload
    if sidecar_errors:
        metadata["ocr_http_sidecar_errors"] = sidecar_errors
    return IntelligentOcrResult(engine=engine_name, blocks=[], metadata=metadata)


def _is_paddlex_layout_parsing_endpoint(endpoint: str) -> bool:
    if not endpoint: return False
    try: return urlparse(endpoint).path.rstrip("/").lower().endswith("/layout-parsing")
    except Exception: return False


def _result_from_paddlex_layout_payload(payload):
    from app.services.ocr_engine.payload_parse import _payload_to_builtin
    builtin = _payload_to_builtin(payload)
    results = []
    if isinstance(builtin, dict):
        result = builtin.get("result")
        if isinstance(result, dict) and isinstance(result.get("layoutParsingResults"), list):
            results = result["layoutParsingResults"]
        elif isinstance(builtin.get("layoutParsingResults"), list):
            results = builtin["layoutParsingResults"]

    blocks, pages, md_parts = [], [], []
    for pi, item in enumerate(results, start=1):
        if not isinstance(item, dict): continue
        md_text = _paddlex_markdown_text(item)
        if md_text: md_parts.append(md_text)
        text = md_text or _paddlex_pruned_text(item.get("prunedResult")) or ""
        pblocks = blocks_from_markdown(text, confidence=0.9, page=pi) if text else []
        if text and not pblocks:
            pblocks = [IntelligentOcrBlock(page=pi, text=clean_text(text), confidence=0.9)]
        blocks.extend(replace(b, stage_source=b.stage_source or "paddleocr_vl",
            model_name=b.model_name or "PaddleOCR-VL-1.5", model_version=b.model_version or "1.5") for b in pblocks)
        pages.append({"page": pi, "block_count": len(pblocks), "has_markdown": bool(md_text)})

    return IntelligentOcrResult(engine="paddleocr_vl_remote:paddlex_layout", blocks=blocks,
        metadata={"ocr_raw_block_count": len(blocks), "model_name": "PaddleOCR-VL-1.5",
                  "model_version": "1.5", "accelerator": "remote_rocm",
                  "pages": pages, "raw_markdown": "\n\n".join(md_parts)})


def _paddlex_markdown_text(item):
    md = item.get("markdown")
    if isinstance(md, dict):
        t = md.get("text")
        if isinstance(t, str) and t.strip(): return t
    t = item.get("markdown")
    return t if isinstance(t, str) and t.strip() else ""


def _paddlex_pruned_text(value):
    if isinstance(value, str): return value
    if isinstance(value, dict):
        for k in ("text", "content", "markdown", "md"):
            i = value.get(k)
            if isinstance(i, str) and i.strip(): return i
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list): return "\n".join(p for p in (_paddlex_pruned_text(i) for i in value) if p)
    return ""


def _mime_type(fp):
    g, _ = mimetypes.guess_type(fp.name)
    if g: return g
    return "application/pdf" if fp.suffix.lower() == ".pdf" else "application/octet-stream"


def _string_list(v):
    return [str(i) for i in v if str(i).strip()] if isinstance(v, list) else []

def _string_dict(v):
    return {str(k): str(i) for k, i in v.items() if str(k).strip() and str(i).strip()} if isinstance(v, dict) else {}
