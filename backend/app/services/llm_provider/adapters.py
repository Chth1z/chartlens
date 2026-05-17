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
from .types import SemanticExtractionProvider, local_collect_evidence_fallback, local_evidence_fallback_usage
from .cache import _llm_cache_key, _read_llm_result_cache, _write_llm_result_cache, _cache_hit_usage, _cache_miss_usage, _evidence_first_cache_key, _read_evidence_candidate_cache, _write_evidence_candidate_cache
from .utils import _base_url_for_profile, _api_keys_for_attempts, _is_rate_limit_or_timeout, _mark_api_key_cooldown, _model_for_profile, _openai_compatible_base_url_candidates, _should_try_next_openai_compatible_response, _should_try_next_openai_compatible_base_url, _chat_response_content, _model_ref
from .payloads import _responses_payload, _responses_evidence_first_payload, _requires_local_evidence_collection, _remote_exposure_policy, _remote_context_mode, _chat_completions_payload, _chat_completions_evidence_first_payload, _anthropic_payload, _anthropic_evidence_first_payload, _gemini_payload, _gemini_evidence_first_payload
from .parsing import _candidates_from_text, _evidence_candidates_from_text, _anthropic_text, _gemini_text

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

    def collect_evidence(
        self,
        *,
        document_context: DocumentContext,
        fields: list[FieldDefinition],
    ) -> dict[str, list[EvidenceCandidate]]:
        cache_key = _evidence_first_cache_key(self.profile, document_context, fields, stage="collect")
        cached = _read_evidence_candidate_cache(cache_key)
        if cached is not None:
            self.last_usage = _cache_hit_usage(cache_key)
            return cached
        remote_policy = _remote_exposure_policy()
        if _requires_local_evidence_collection(remote_policy):
            from app.services.evidence_first import collect_local_evidence

            result = collect_local_evidence(document_context, fields)
            self.last_usage = {
                "input_tokens": 0,
                "output_tokens": 0,
                "cached_input_tokens": 0,
                "cost_usd": 0.0,
                "remote_context_mode": _remote_context_mode(remote_policy),
                "remote_skipped_reason": "remote_full_context_disabled",
                **_cache_miss_usage(cache_key),
            }
            _write_evidence_candidate_cache(cache_key, result)
            return result
        payload = _responses_evidence_first_payload(
            document_context=document_context,
            fields=fields,
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
            raise last_error or RuntimeError("OpenAI Responses evidence collection failed")
        usage = getattr(response, "usage", None)
        input_details = getattr(usage, "input_tokens_details", None) or getattr(usage, "prompt_tokens_details", None)
        self.last_usage = {
            "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
            "cached_input_tokens": int(getattr(input_details, "cached_tokens", 0) or 0),
            "cost_usd": 0.0,
            **_cache_miss_usage(cache_key),
        }
        result = _evidence_candidates_from_text(response.output_text)
        _write_evidence_candidate_cache(cache_key, result)
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

    def collect_evidence(
        self,
        *,
        document_context: DocumentContext,
        fields: list[FieldDefinition],
    ) -> dict[str, list[EvidenceCandidate]]:
        """Real implementation: call /chat/completions with the
        evidence-first JSON schema. Falls back to local rule extraction
        if the remote exposure policy disallows full document context,
        the call fails for any non-recoverable reason, or the response
        is malformed JSON.

        E1-011 Phase 2 (2026-05-18). Replaces the explicit-delegation
        shim from Phase 1.
        """
        cache_key = _evidence_first_cache_key(self.profile, document_context, fields, stage="collect")
        cached = _read_evidence_candidate_cache(cache_key)
        if cached is not None:
            self.last_usage = _cache_hit_usage(cache_key)
            return cached

        remote_policy = _remote_exposure_policy()
        if _requires_local_evidence_collection(remote_policy):
            # Privacy boundary forbids sending the full document context to
            # the remote model. Return local-rule evidence and surface the
            # reason in the observability ledger.
            result = local_collect_evidence_fallback(document_context, fields)
            self.last_usage = {
                **local_evidence_fallback_usage(),
                "remote_context_mode": _remote_context_mode(remote_policy),
                "remote_skipped_reason": "remote_full_context_disabled",
                **_cache_miss_usage(cache_key),
            }
            _write_evidence_candidate_cache(cache_key, result)
            return result

        payload = _chat_completions_evidence_first_payload(
            document_context=document_context,
            fields=fields,
            model=self.model,
            profile=self.profile,
        )

        last_error: Exception | None = None
        response = None
        content = None
        for api_key in _api_keys_for_attempts(self.profile, self.api_keys):
            for index, base_url in enumerate(self.base_urls):
                client = self.client_class(
                    api_key=api_key, base_url=base_url, timeout=settings.openai_timeout_seconds
                )
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
                        # Permanent failure (auth, model-not-found, etc.).
                        # Degrade to local rule extraction so the pipeline
                        # never returns nothing on a transient remote bug.
                        return self._chat_evidence_local_fallback(
                            document_context=document_context,
                            fields=fields,
                            cache_key=cache_key,
                            failure=exc,
                            failure_reason="permanent_error",
                        )
                    _mark_api_key_cooldown(self.profile, api_key, exc)
                    break
            if response is not None:
                break

        if response is None or not content:
            return self._chat_evidence_local_fallback(
                document_context=document_context,
                fields=fields,
                cache_key=cache_key,
                failure=last_error,
                failure_reason="no_response",
            )

        try:
            result = _evidence_candidates_from_text(content)
        except Exception as exc:
            return self._chat_evidence_local_fallback(
                document_context=document_context,
                fields=fields,
                cache_key=cache_key,
                failure=exc,
                failure_reason="malformed_json",
            )

        usage = getattr(response, "usage", None)
        prompt_cache_hit_tokens = 0
        if usage is not None:
            details = getattr(usage, "prompt_tokens_details", None)
            if details is not None:
                prompt_cache_hit_tokens = int(getattr(details, "cached_tokens", 0) or 0)
            # DeepSeek surfaces prompt-cache hits via top-level fields
            # named prompt_cache_hit_tokens / prompt_cache_miss_tokens
            # (per api-docs.deepseek.com/quick_start/pricing). Fall back
            # to those when prompt_tokens_details is absent.
            if not prompt_cache_hit_tokens:
                prompt_cache_hit_tokens = int(getattr(usage, "prompt_cache_hit_tokens", 0) or 0)

        self.last_usage = {
            "input_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "output_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            "cached_input_tokens": prompt_cache_hit_tokens,
            "cost_usd": 0.0,
            "evidence_collection_method": "remote_chat_completions",
            **_cache_miss_usage(cache_key),
        }
        _write_evidence_candidate_cache(cache_key, result)
        return result

    def _chat_evidence_local_fallback(
        self,
        *,
        document_context: DocumentContext,
        fields: list[FieldDefinition],
        cache_key: str,
        failure: Exception | None,
        failure_reason: str,
    ) -> dict[str, list[EvidenceCandidate]]:
        """Shared graceful-degradation path for collect_evidence.

        Returns local rule extraction results instead of failing. Surfaces
        the upstream failure reason in last_usage so the durable
        observability ledger records WHY the remote call did not happen.
        Does not write the cache because the result is not authoritative
        for this profile / model.
        """
        result = local_collect_evidence_fallback(document_context, fields)
        self.last_usage = {
            **local_evidence_fallback_usage(),
            "remote_skipped_reason": failure_reason,
            "remote_failure": safe_error_message(failure) if failure is not None else None,
            **_cache_miss_usage(cache_key),
        }
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

    def collect_evidence(
        self,
        *,
        document_context: DocumentContext,
        fields: list[FieldDefinition],
    ) -> dict[str, list[EvidenceCandidate]]:
        """Real implementation: call Anthropic Messages API with the
        evidence-first JSON contract. Falls back to local rule extraction
        when remote exposure policy disallows full document context, when
        the call fails permanently (auth, model-not-found), or when the
        response is not valid JSON.

        E1-011 Phase 3 (2026-05-18). Replaces the explicit-delegation
        shim from Phase 1.
        """
        cache_key = _evidence_first_cache_key(self.profile, document_context, fields, stage="collect")
        cached = _read_evidence_candidate_cache(cache_key)
        if cached is not None:
            self.last_usage = _cache_hit_usage(cache_key)
            return cached

        remote_policy = _remote_exposure_policy()
        if _requires_local_evidence_collection(remote_policy):
            result = local_collect_evidence_fallback(document_context, fields)
            self.last_usage = {
                **local_evidence_fallback_usage(),
                "remote_context_mode": _remote_context_mode(remote_policy),
                "remote_skipped_reason": "remote_full_context_disabled",
                **_cache_miss_usage(cache_key),
            }
            _write_evidence_candidate_cache(cache_key, result)
            return result

        payload = _anthropic_evidence_first_payload(
            document_context=document_context,
            fields=fields,
            model=self.model,
            profile=self.profile,
        )

        last_error: Exception | None = None
        data: dict[str, Any] | None = None
        for api_key in _api_keys_for_attempts(self.profile, self.api_keys):
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            try:
                with httpx.Client(timeout=settings.openai_timeout_seconds) as client:
                    response = client.post(
                        f"{self.base_url}/v1/messages", headers=headers, json=payload
                    )
                    response.raise_for_status()
                    data = response.json()
                break
            except Exception as exc:
                last_error = exc
                if not _is_rate_limit_or_timeout(exc):
                    return self._anthropic_evidence_local_fallback(
                        document_context=document_context,
                        fields=fields,
                        cache_key=cache_key,
                        failure=exc,
                        failure_reason="permanent_error",
                    )
                _mark_api_key_cooldown(self.profile, api_key, exc)

        if data is None:
            return self._anthropic_evidence_local_fallback(
                document_context=document_context,
                fields=fields,
                cache_key=cache_key,
                failure=last_error,
                failure_reason="no_response",
            )

        try:
            text = _anthropic_text(data)
            result = _evidence_candidates_from_text(text)
        except Exception as exc:
            return self._anthropic_evidence_local_fallback(
                document_context=document_context,
                fields=fields,
                cache_key=cache_key,
                failure=exc,
                failure_reason="malformed_json",
            )

        usage = data.get("usage", {}) or {}
        self.last_usage = {
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "cached_input_tokens": int(usage.get("cache_read_input_tokens") or 0),
            "cost_usd": 0.0,
            "evidence_collection_method": "remote_anthropic_messages",
            **_cache_miss_usage(cache_key),
        }
        _write_evidence_candidate_cache(cache_key, result)
        return result

    def _anthropic_evidence_local_fallback(
        self,
        *,
        document_context: DocumentContext,
        fields: list[FieldDefinition],
        cache_key: str,
        failure: Exception | None,
        failure_reason: str,
    ) -> dict[str, list[EvidenceCandidate]]:
        result = local_collect_evidence_fallback(document_context, fields)
        self.last_usage = {
            **local_evidence_fallback_usage(),
            "remote_skipped_reason": failure_reason,
            "remote_failure": safe_error_message(failure) if failure is not None else None,
            **_cache_miss_usage(cache_key),
        }
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

    def collect_evidence(
        self,
        *,
        document_context: DocumentContext,
        fields: list[FieldDefinition],
    ) -> dict[str, list[EvidenceCandidate]]:
        """Real implementation: call Gemini generateContent with
        responseMimeType=application/json + responseSchema for the
        evidence-first JSON contract. Falls back to local rule
        extraction on policy block, permanent error, or malformed JSON.

        E1-011 Phase 3 (2026-05-18). Replaces the explicit-delegation
        shim from Phase 1.
        """
        cache_key = _evidence_first_cache_key(self.profile, document_context, fields, stage="collect")
        cached = _read_evidence_candidate_cache(cache_key)
        if cached is not None:
            self.last_usage = _cache_hit_usage(cache_key)
            return cached

        remote_policy = _remote_exposure_policy()
        if _requires_local_evidence_collection(remote_policy):
            result = local_collect_evidence_fallback(document_context, fields)
            self.last_usage = {
                **local_evidence_fallback_usage(),
                "remote_context_mode": _remote_context_mode(remote_policy),
                "remote_skipped_reason": "remote_full_context_disabled",
                **_cache_miss_usage(cache_key),
            }
            _write_evidence_candidate_cache(cache_key, result)
            return result

        payload = _gemini_evidence_first_payload(
            document_context=document_context,
            fields=fields,
            model=self.model,
            profile=self.profile,
        )

        last_error: Exception | None = None
        data: dict[str, Any] | None = None
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
                    return self._gemini_evidence_local_fallback(
                        document_context=document_context,
                        fields=fields,
                        cache_key=cache_key,
                        failure=exc,
                        failure_reason="permanent_error",
                    )
                _mark_api_key_cooldown(self.profile, api_key, exc)

        if data is None:
            return self._gemini_evidence_local_fallback(
                document_context=document_context,
                fields=fields,
                cache_key=cache_key,
                failure=last_error,
                failure_reason="no_response",
            )

        try:
            text = _gemini_text(data)
            result = _evidence_candidates_from_text(text)
        except Exception as exc:
            return self._gemini_evidence_local_fallback(
                document_context=document_context,
                fields=fields,
                cache_key=cache_key,
                failure=exc,
                failure_reason="malformed_json",
            )

        usage = data.get("usageMetadata", {}) or {}
        self.last_usage = {
            "input_tokens": int(usage.get("promptTokenCount") or 0),
            "output_tokens": int(usage.get("candidatesTokenCount") or 0),
            "cached_input_tokens": int(usage.get("cachedContentTokenCount") or 0),
            "cost_usd": 0.0,
            "evidence_collection_method": "remote_gemini_generate_content",
            **_cache_miss_usage(cache_key),
        }
        _write_evidence_candidate_cache(cache_key, result)
        return result

    def _gemini_evidence_local_fallback(
        self,
        *,
        document_context: DocumentContext,
        fields: list[FieldDefinition],
        cache_key: str,
        failure: Exception | None,
        failure_reason: str,
    ) -> dict[str, list[EvidenceCandidate]]:
        result = local_collect_evidence_fallback(document_context, fields)
        self.last_usage = {
            **local_evidence_fallback_usage(),
            "remote_skipped_reason": failure_reason,
            "remote_failure": safe_error_message(failure) if failure is not None else None,
            **_cache_miss_usage(cache_key),
        }
        return result
