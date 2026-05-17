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
_API_KEY_COOLDOWN_UNTIL: dict[tuple[str, str], float] = {}

def _model_for_profile(profile) -> str:
    if profile.profile_id == "openai_compatible_custom" and settings.compatible_model:
        return settings.compatible_model
    return profile.model


def _base_url_for_profile(profile) -> str | None:
    if profile.profile_id.startswith("deepseek"):
        return settings.deepseek_base_url or profile.base_url
    if profile.profile_id == "openai_compatible_custom" and settings.compatible_base_url:
        return settings.compatible_base_url
    return profile.base_url


def _openai_compatible_base_url_candidates(base_url: str) -> list[str]:
    base = base_url.rstrip("/")
    candidates = [base]
    parsed = urlparse(base)
    if parsed.scheme and parsed.netloc and parsed.path.rstrip("/") in {"", "/"}:
        candidates.append(f"{base}/v1")
    return list(dict.fromkeys(candidates))


def _should_try_next_openai_compatible_base_url(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code in {404, 405}:
        return True
    message = str(exc).lower()
    return "404" in message or "not found" in message or "method not allowed" in message


def _should_try_next_openai_compatible_response(content: str) -> bool:
    stripped = content.lstrip().lower()
    return stripped.startswith("<!doctype html") or stripped.startswith("<html")


def _chat_response_content(response: Any) -> str:
    if isinstance(response, str):
        return _content_from_response_string(response)
    if isinstance(response, dict):
        return _content_from_response_mapping(response)
    choices = getattr(response, "choices", None)
    if choices:
        return _content_from_choice(choices[0])
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str):
        return output_text
    if hasattr(response, "model_dump"):
        dumped = response.model_dump()
        if isinstance(dumped, dict):
            return _content_from_response_mapping(dumped)
    raise ValueError(f"OpenAI-compatible response did not contain choices; got {type(response).__name__}")


def _content_from_response_string(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return ""
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped
    if isinstance(parsed, dict) and "choices" in parsed:
        return _content_from_response_mapping(parsed)
    return stripped


def _content_from_response_mapping(response: dict[str, Any]) -> str:
    if isinstance(response.get("results"), list):
        return json.dumps(response, ensure_ascii=False)
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        return _content_from_choice(choices[0])
    for key in ("output_text", "content", "text"):
        value = response.get(key)
        if value is not None:
            return _content_to_text(value)
    message = response.get("message")
    if message is not None:
        return _content_from_message(message)
    raise ValueError("OpenAI-compatible response did not contain choices")


def _content_from_choice(choice: Any) -> str:
    if isinstance(choice, dict):
        if "message" in choice:
            return _content_from_message(choice["message"])
        for key in ("content", "text"):
            if key in choice:
                return _content_to_text(choice[key])
    message = getattr(choice, "message", None)
    if message is not None:
        return _content_from_message(message)
    content = getattr(choice, "content", None)
    if content is not None:
        return _content_to_text(content)
    text = getattr(choice, "text", None)
    if text is not None:
        return _content_to_text(text)
    raise ValueError("OpenAI-compatible choice did not contain message content")


def _content_from_message(message: Any) -> str:
    if isinstance(message, str):
        return message
    if isinstance(message, dict):
        return _content_to_text(message.get("content", ""))
    return _content_to_text(getattr(message, "content", ""))


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text is not None:
                    parts.append(_content_to_text(text))
        return "\n".join(part for part in parts if part).strip()
    return str(content)


def _model_ref(profile) -> str:
    return profile.model_ref or f"{profile.provider_id or profile.profile_id}/{profile.model}"


def _format_provider_failure(profile, exc: Exception) -> str:
    return f"{_model_ref(profile)}: {type(exc).__name__}: {safe_error_message(exc)}"


def _api_keys_for_attempts(profile, api_keys: list[str]) -> list[str]:
    now = time.monotonic()
    available: list[str] = []
    for api_key in api_keys:
        cooldown_until = _API_KEY_COOLDOWN_UNTIL.get(_api_key_cooldown_key(profile, api_key))
        if cooldown_until and cooldown_until > now:
            continue
        available.append(api_key)
    return available or api_keys


def _mark_api_key_cooldown(profile, api_key: str, exc: Exception) -> None:
    cooldown_seconds = max(float(settings.model_key_cooldown_seconds or 0), 0.0)
    if cooldown_seconds <= 0 or not _is_rate_limit_or_timeout(exc):
        return
    _API_KEY_COOLDOWN_UNTIL[_api_key_cooldown_key(profile, api_key)] = time.monotonic() + cooldown_seconds


def _api_key_cooldown_key(profile, api_key: str) -> tuple[str, str]:
    provider_id = getattr(profile, "provider_id", None) or getattr(profile, "profile_id", "unknown")
    fingerprint = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    return str(provider_id), fingerprint


def _is_rate_limit_or_timeout(exc: Exception) -> bool:
    text = str(exc).lower()
    status = getattr(exc, "status_code", None)
    return bool(
        status in {408, 409, 429, 500, 502, 503, 504}
        or any(
            marker in text
            for marker in (
                "rate limit",
                "rate_limit",
                "quota",
                "throttl",
                "too many",
                "timeout",
                "timed out",
                "overloaded",
                "busy",
                "concurrency",
                "resource exhausted",
                "internal server error",
                "upstream error",
                "backend error",
            )
        )
    )


def _is_failover_worthy(exc: Exception) -> bool:
    text = str(exc).lower()
    status = getattr(exc, "status_code", None)
    return bool(
        _is_rate_limit_or_timeout(exc)
        or status in {401, 402, 403, 404}
        or any(
            marker in text
            for marker in (
                "api key",
                "unauthorized",
                "forbidden",
                "insufficient",
                "credit",
                "billing",
                "not found",
                "model",
                "base_url",
                "required",
            )
        )
    )

