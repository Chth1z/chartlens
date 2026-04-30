from __future__ import annotations

import json
import re
import hashlib
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config_loader import load_document_profile, load_extraction_schema
from app.core.settings import settings
from app.domain.models import (
    DocumentIR,
    DocumentIRBlock,
    ExtractedFact,
    ExtractionCandidate,
    FieldDefinition,
    FieldGroup,
)
from app.services.evidence import build_evidence_packs
from app.services.domain_profile import extraction_rules, extraction_system_prompt
from app.services.model_auth import api_keys_for_profile
from app.services.model_selection import get_active_model_profile, resolve_model_chain
from app.services.safe_errors import safe_error_message

_API_KEY_COOLDOWN_UNTIL: dict[tuple[str, str], float] = {}
PROMPT_VERSION = "eyex-evidence-pack-v3"
DEFAULT_PROVIDER_GROUP_BUDGET = 3200


class SemanticExtractionProvider(ABC):
    name = "semantic-provider"
    route = "unknown"
    last_usage: dict[str, Any] = {}

    @abstractmethod
    def extract_group(
        self,
        *,
        document_ir: DocumentIR,
        group: FieldGroup,
        fields: list[FieldDefinition],
        blocks: list[DocumentIRBlock],
    ) -> list[ExtractionCandidate]:
        raise NotImplementedError


class OpenAIResponsesProvider(SemanticExtractionProvider):
    name = "openai-responses-structured"
    route = "online_llm"

    def __init__(self, profile=None) -> None:
        self.profile = profile or get_active_model_profile()
        self.api_keys = api_keys_for_profile(self.profile)
        if not self.api_keys:
            raise RuntimeError("EYEX_OPENAI_API_KEY is required for OpenAIResponsesProvider")
        from openai import OpenAI

        self.client_class = OpenAI
        self.model = self.profile.model or settings.openai_model
        self.base_url = _base_url_for_profile(self.profile)

    def extract_group(
        self,
        *,
        document_ir: DocumentIR,
        group: FieldGroup,
        fields: list[FieldDefinition],
        blocks: list[DocumentIRBlock],
    ) -> list[ExtractionCandidate]:
        cache_key = _llm_cache_key(self.profile, document_ir, group, fields, blocks)
        cached = _read_llm_result_cache(cache_key)
        if cached is not None:
            self.last_usage = _cache_hit_usage(cache_key)
            return cached
        payload = _responses_payload(
            document_ir=document_ir,
            group=group,
            fields=fields,
            blocks=blocks,
            model=self.model,
            profile=self.profile,
        )
        last_error: Exception | None = None
        for api_key in _api_keys_for_attempts(self.profile, self.api_keys):
            client_kwargs: dict[str, Any] = {"api_key": api_key, "timeout": settings.openai_timeout_seconds}
            if self.base_url:
                client_kwargs["base_url"] = self.base_url
            client = self.client_class(**client_kwargs)
            try:
                response = client.responses.create(**payload)
                break
            except Exception as exc:
                last_error = exc
                if not _is_rate_limit_or_timeout(exc):
                    raise
                _mark_api_key_cooldown(self.profile, api_key, exc)
        else:
            raise last_error or RuntimeError("OpenAI Responses request failed")
        usage = getattr(response, "usage", None)
        input_details = getattr(usage, "input_tokens_details", None) or getattr(usage, "prompt_tokens_details", None)
        self.last_usage = {
            "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
            "cached_input_tokens": int(getattr(input_details, "cached_tokens", 0) or 0),
            "cost_usd": 0.0,
            **_cache_miss_usage(cache_key),
        }
        result = _candidates_from_text(response.output_text)
        _write_llm_result_cache(cache_key, result)
        return result


class OpenAICompatibleChatProvider(SemanticExtractionProvider):
    name = "openai-compatible-chat"
    route = "compatible_llm"

    def __init__(self, profile=None) -> None:
        self.profile = profile or get_active_model_profile()
        self.api_keys = api_keys_for_profile(self.profile)
        if not self.api_keys:
            raise RuntimeError(f"{self.profile.api_key_env or 'API key'} is required for {self.profile.profile_id}")
        base_url = _base_url_for_profile(self.profile)
        if not base_url:
            raise RuntimeError(f"base_url is required for {self.profile.profile_id}")
        from openai import OpenAI

        self.client_class = OpenAI
        self.base_urls = _openai_compatible_base_url_candidates(base_url)
        self.base_url = self.base_urls[0]
        self.model = _model_for_profile(self.profile)
        self.name = f"{self.profile.profile_id}-chat"

    def extract_group(
        self,
        *,
        document_ir: DocumentIR,
        group: FieldGroup,
        fields: list[FieldDefinition],
        blocks: list[DocumentIRBlock],
    ) -> list[ExtractionCandidate]:
        cache_key = _llm_cache_key(self.profile, document_ir, group, fields, blocks)
        cached = _read_llm_result_cache(cache_key)
        if cached is not None:
            self.last_usage = _cache_hit_usage(cache_key)
            return cached
        payload = _chat_completions_payload(
            document_ir=document_ir,
            group=group,
            fields=fields,
            blocks=blocks,
            model=self.model,
            profile=self.profile,
        )
        last_error: Exception | None = None
        response = None
        content = None
        for api_key in _api_keys_for_attempts(self.profile, self.api_keys):
            for index, base_url in enumerate(self.base_urls):
                client = self.client_class(api_key=api_key, base_url=base_url, timeout=settings.openai_timeout_seconds)
                try:
                    response = client.chat.completions.create(**payload)
                    content = _chat_response_content(response)
                    has_next_base_url = index < len(self.base_urls) - 1
                    if has_next_base_url and _should_try_next_openai_compatible_response(content):
                        response = None
                        content = None
                        continue
                    self.base_url = base_url
                    break
                except Exception as exc:
                    last_error = exc
                    has_next_base_url = index < len(self.base_urls) - 1
                    if has_next_base_url and _should_try_next_openai_compatible_base_url(exc):
                        continue
                    if not _is_rate_limit_or_timeout(exc):
                        raise
                    _mark_api_key_cooldown(self.profile, api_key, exc)
                    break
            if response is not None:
                break
        else:
            raise last_error or RuntimeError("OpenAI-compatible request failed")
        usage = getattr(response, "usage", None)
        self.last_usage = {
            "input_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "output_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            "cached_input_tokens": 0,
            "cost_usd": 0.0,
            **_cache_miss_usage(cache_key),
        }
        if not content:
            raise ValueError("OpenAI-compatible response did not contain message content")
        result = _candidates_from_text(content)
        _write_llm_result_cache(cache_key, result)
        return result


class AnthropicMessagesProvider(SemanticExtractionProvider):
    name = "anthropic-messages"
    route = "anthropic_llm"

    def __init__(self, profile=None) -> None:
        self.profile = profile or get_active_model_profile()
        self.api_keys = api_keys_for_profile(self.profile)
        if not self.api_keys:
            raise RuntimeError(f"API key is required for {_model_ref(self.profile)}")
        self.base_url = (_base_url_for_profile(self.profile) or "https://api.anthropic.com").rstrip("/")
        self.model = _model_for_profile(self.profile)

    def extract_group(
        self,
        *,
        document_ir: DocumentIR,
        group: FieldGroup,
        fields: list[FieldDefinition],
        blocks: list[DocumentIRBlock],
    ) -> list[ExtractionCandidate]:
        cache_key = _llm_cache_key(self.profile, document_ir, group, fields, blocks)
        cached = _read_llm_result_cache(cache_key)
        if cached is not None:
            self.last_usage = _cache_hit_usage(cache_key)
            return cached
        payload = _anthropic_payload(
            document_ir=document_ir,
            group=group,
            fields=fields,
            blocks=blocks,
            model=self.model,
            profile=self.profile,
        )
        last_error: Exception | None = None
        for api_key in _api_keys_for_attempts(self.profile, self.api_keys):
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            try:
                with httpx.Client(timeout=settings.openai_timeout_seconds) as client:
                    response = client.post(f"{self.base_url}/v1/messages", headers=headers, json=payload)
                    response.raise_for_status()
                    data = response.json()
                break
            except Exception as exc:
                last_error = exc
                if not _is_rate_limit_or_timeout(exc):
                    raise
                _mark_api_key_cooldown(self.profile, api_key, exc)
        else:
            raise last_error or RuntimeError("Anthropic request failed")
        usage = data.get("usage", {})
        self.last_usage = {
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "cached_input_tokens": int(usage.get("cache_read_input_tokens") or 0),
            "cost_usd": 0.0,
            **_cache_miss_usage(cache_key),
        }
        result = _candidates_from_text(_anthropic_text(data))
        _write_llm_result_cache(cache_key, result)
        return result


class GoogleGeminiProvider(SemanticExtractionProvider):
    name = "google-gemini"
    route = "gemini_llm"

    def __init__(self, profile=None) -> None:
        self.profile = profile or get_active_model_profile()
        self.api_keys = api_keys_for_profile(self.profile)
        if not self.api_keys:
            raise RuntimeError(f"API key is required for {_model_ref(self.profile)}")
        self.base_url = (_base_url_for_profile(self.profile) or "https://generativelanguage.googleapis.com").rstrip("/")
        self.model = _model_for_profile(self.profile)

    def extract_group(
        self,
        *,
        document_ir: DocumentIR,
        group: FieldGroup,
        fields: list[FieldDefinition],
        blocks: list[DocumentIRBlock],
    ) -> list[ExtractionCandidate]:
        cache_key = _llm_cache_key(self.profile, document_ir, group, fields, blocks)
        cached = _read_llm_result_cache(cache_key)
        if cached is not None:
            self.last_usage = _cache_hit_usage(cache_key)
            return cached
        payload = _gemini_payload(
            document_ir=document_ir,
            group=group,
            fields=fields,
            blocks=blocks,
            model=self.model,
            profile=self.profile,
        )
        last_error: Exception | None = None
        for api_key in _api_keys_for_attempts(self.profile, self.api_keys):
            try:
                with httpx.Client(timeout=settings.openai_timeout_seconds) as client:
                    response = client.post(
                        f"{self.base_url}/v1beta/models/{self.model}:generateContent",
                        params={"key": api_key},
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()
                break
            except Exception as exc:
                last_error = exc
                if not _is_rate_limit_or_timeout(exc):
                    raise
                _mark_api_key_cooldown(self.profile, api_key, exc)
        else:
            raise last_error or RuntimeError("Gemini request failed")
        usage = data.get("usageMetadata", {})
        self.last_usage = {
            "input_tokens": int(usage.get("promptTokenCount") or 0),
            "output_tokens": int(usage.get("candidatesTokenCount") or 0),
            "cached_input_tokens": int(usage.get("cachedContentTokenCount") or 0),
            "cost_usd": 0.0,
            **_cache_miss_usage(cache_key),
        }
        result = _candidates_from_text(_gemini_text(data))
        _write_llm_result_cache(cache_key, result)
        return result


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


class ModelFallbackProvider(SemanticExtractionProvider):
    name = "openclaw-style-model-fallback"
    route = "model_fallback"

    def __init__(self, profiles) -> None:
        self.profiles = profiles

    def extract_group(
        self,
        *,
        document_ir: DocumentIR,
        group: FieldGroup,
        fields: list[FieldDefinition],
        blocks: list[DocumentIRBlock],
    ) -> list[ExtractionCandidate]:
        failures: list[str] = []
        for profile in self.profiles:
            try:
                provider = _provider_for_profile(profile)
                result = provider.extract_group(document_ir=document_ir, group=group, fields=fields, blocks=blocks)
                self.name = provider.name
                self.route = provider.route
                self.last_usage = {
                    **provider.last_usage,
                    "fallback_attempts": len(failures),
                }
                if failures:
                    self.last_usage["fallback_errors"] = failures
                return result
            except Exception as exc:
                failures.append(_format_provider_failure(profile, exc))
                if not _is_failover_worthy(exc):
                    break
        if fields:
            result = [
                _unknown_model_unavailable(field, "LLM_PROVIDER_FAILED", "语义模型链路不可用，复杂字段保持 unknown 并进入复核。")
                for field in fields
            ]
            self.name = "unknown-after-model-fallback"
            self.route = "unknown_after_model_fallback"
        else:
            fallback = ConservativeLocalProvider()
            result = fallback.extract_group(document_ir=document_ir, group=group, fields=fields, blocks=blocks)
            self.name = fallback.name
            self.route = "local_after_model_fallback"
        self.last_usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_input_tokens": 0,
            "cost_usd": 0.0,
            "fallback_attempts": len(failures),
            "fallback_failures": len(failures),
            "fallback_errors": failures,
        }
        return result


def build_semantic_provider() -> SemanticExtractionProvider:
    active = get_active_model_profile()
    if active.provider == "disabled" or settings.llm_mode == "disabled":
        return ConservativeLocalProvider()
    return ModelFallbackProvider(resolve_model_chain(active))


def _provider_for_profile(profile) -> SemanticExtractionProvider:
    if profile.provider == "disabled":
        return ConservativeLocalProvider()
    if profile.provider == "openai_responses" and settings.llm_mode in {"auto", "online"}:
        return OpenAIResponsesProvider(profile)
    if profile.provider == "openai_compatible" and settings.llm_mode in {"auto", "online", "local"}:
        return OpenAICompatibleChatProvider(profile)
    if profile.provider == "anthropic_messages" and settings.llm_mode in {"auto", "online"}:
        return AnthropicMessagesProvider(profile)
    if profile.provider == "google_gemini" and settings.llm_mode in {"auto", "online"}:
        return GoogleGeminiProvider(profile)
    raise RuntimeError(f"Model profile is not runnable in current mode: {_model_ref(profile)}")


def _responses_payload(
    *,
    document_ir: DocumentIR,
    group: FieldGroup,
    fields: list[FieldDefinition],
    blocks: list[DocumentIRBlock],
    model: str,
    profile=None,
) -> dict[str, Any]:
    model_profile = profile or get_active_model_profile()
    document_profile = _document_profile_for_ir(document_ir)
    user_payload = _llm_user_payload(document_ir=document_ir, group=group, fields=fields, blocks=blocks)
    payload: dict[str, Any] = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": extraction_system_prompt(document_profile),
            },
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "eyex_group_extraction",
                "strict": True,
                "schema": _response_schema(),
            }
        },
        "store": False,
        "prompt_cache_key": model_profile.prompt_cache_key,
        "max_output_tokens": model_profile.max_output_tokens,
    }
    effort = model_profile.reasoning_effort or settings.openai_reasoning_effort
    if effort:
        payload["reasoning"] = {"effort": effort}
    return payload


def _chat_completions_payload(
    *,
    document_ir: DocumentIR,
    group: FieldGroup,
    fields: list[FieldDefinition],
    blocks: list[DocumentIRBlock],
    model: str,
    profile,
) -> dict[str, Any]:
    document_profile = _document_profile_for_ir(document_ir)
    user_payload = _llm_user_payload(document_ir=document_ir, group=group, fields=fields, blocks=blocks)
    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": f"{extraction_system_prompt(document_profile)} You must output JSON only.",
            },
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": profile.temperature,
        "max_tokens": profile.max_output_tokens,
    }


def _anthropic_payload(
    *,
    document_ir: DocumentIR,
    group: FieldGroup,
    fields: list[FieldDefinition],
    blocks: list[DocumentIRBlock],
    model: str,
    profile,
) -> dict[str, Any]:
    document_profile = _document_profile_for_ir(document_ir)
    user_payload = _llm_user_payload(document_ir=document_ir, group=group, fields=fields, blocks=blocks)
    return {
        "model": model,
        "max_tokens": profile.max_output_tokens,
        "temperature": profile.temperature,
        "system": f"{extraction_system_prompt(document_profile)} You must output one JSON object only.",
        "messages": [{"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}],
    }


def _gemini_payload(
    *,
    document_ir: DocumentIR,
    group: FieldGroup,
    fields: list[FieldDefinition],
    blocks: list[DocumentIRBlock],
    model: str,
    profile,
) -> dict[str, Any]:
    del model
    document_profile = _document_profile_for_ir(document_ir)
    user_payload = _llm_user_payload(document_ir=document_ir, group=group, fields=fields, blocks=blocks)
    return {
        "systemInstruction": {
            "parts": [
                {
                    "text": f"{extraction_system_prompt(document_profile)} You must output one JSON object only."
                }
            ]
        },
        "contents": [{"role": "user", "parts": [{"text": json.dumps(user_payload, ensure_ascii=False)}]}],
        "generationConfig": {
            "temperature": profile.temperature,
            "maxOutputTokens": profile.max_output_tokens,
            "responseMimeType": "application/json",
        },
    }


def _llm_user_payload(
    *,
    document_ir: DocumentIR,
    group: FieldGroup,
    fields: list[FieldDefinition],
    blocks: list[DocumentIRBlock],
) -> dict[str, Any]:
    document_profile = _document_profile_for_ir(document_ir)
    return {
        "document_id": document_ir.document_id,
        "profile_id": document_ir.profile_id,
        "field_group": group.model_dump(),
        "rules": ["Return one valid JSON object only, with a top-level results array.", *extraction_rules(document_profile)],
        "output_schema": _response_schema(),
        "fields": [_field_prompt_spec(field) for field in fields],
        "evidence_packs": _field_evidence_pack_payload(fields, blocks),
    }


def _document_profile_for_ir(document_ir: DocumentIR):
    try:
        return load_document_profile(document_ir.profile_id)
    except Exception:
        return None


def _field_prompt_spec(field: FieldDefinition) -> dict[str, Any]:
    return {
        "key": field.key,
        "label": field.label,
        "type": field.type,
        "allowed_codes": field.allowed_codes,
        "source_sections": field.source_sections,
        "excluded_sections": field.excluded_sections,
        "synonyms": field.synonyms,
        "negation_terms": field.negation_terms,
        "code_map": field.code_map,
        "extract_mode": field.extract_mode,
        "rule_patterns": [pattern.model_dump() for pattern in field.rule_patterns],
    }


def _field_evidence_pack_payload(fields: list[FieldDefinition], blocks: list[DocumentIRBlock]) -> dict[str, list[dict[str, Any]]]:
    payload: dict[str, list[dict[str, Any]]] = {}
    for field in fields:
        payload[field.key] = [
            {
                "pack_hash": item.pack_hash,
                "rank": item.rank,
                "block_id": item.block_id,
                "text": item.text,
                "context_text": item.context_text,
                "page": item.page,
                "section_label": item.section_label,
                "document_kind": item.document_kind,
                "ocr_confidence": item.ocr_confidence,
                "score": item.score,
                "match_terms": item.match_terms,
                "score_reason": item.score_reason,
                "negated": item.negated,
                "uncertain": item.uncertain,
                "family_context": item.family_context,
                "token_estimate": item.token_estimate,
                "neighbor_block_ids": item.neighbor_block_ids,
            }
            for item in build_evidence_packs(None, field, blocks=blocks, group_budget=DEFAULT_PROVIDER_GROUP_BUDGET)
        ]
    return payload


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


def _candidates_from_text(text: str) -> list[ExtractionCandidate]:
    parsed = _parse_llm_json_object(text)
    results = parsed.get("results") if isinstance(parsed, dict) else None
    if not isinstance(results, list):
        raise ValueError("LLM response must contain results array")
    return [ExtractionCandidate.model_validate(_normalize_candidate_payload(item)) for item in results if isinstance(item, dict)]


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


def _unknown_model_unavailable(field: FieldDefinition, error_code: str, summary: str) -> ExtractionCandidate:
    return ExtractionCandidate(
        field_key=field.key,
        field_group_key=field.field_group_key,
        normalized_code="unknown",
        status="error",
        confidence=0.0,
        evidence_type="no_evidence",
        reasoning_summary=summary,
        review_required=True,
        error_code=error_code,
        provenance={"source": "model_fallback"},
        acceptance_reason=error_code,
        risk_level="high",
        validation_state="needs_review",
    )


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
