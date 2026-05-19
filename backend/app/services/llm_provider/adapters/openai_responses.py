from __future__ import annotations
from typing import Any

from app.core.settings import settings
from app.domain.models import (
    DocumentIR, DocumentContext, DocumentIRBlock, EvidenceCandidate,
    ExtractionCandidate, FieldDefinition, FieldGroup,
)
from app.services.model_selection import get_active_model_profile
from app.services.llm_provider import adapters as _pkg
from ..types import SemanticExtractionProvider
from ..utils import _base_url_for_profile, _api_keys_for_attempts, _is_rate_limit_or_timeout, _mark_api_key_cooldown
from ..payloads import _requires_local_evidence_collection, _remote_exposure_policy, _remote_context_mode
from ..cache import _cache_hit_usage, _cache_miss_usage, _evidence_first_cache_key
from ..parsing import _candidates_from_text, _evidence_candidates_from_text


class OpenAIResponsesProvider(SemanticExtractionProvider):
    name = "openai-responses-structured"
    route = "online_llm"

    def __init__(self, profile=None) -> None:
        self.profile = profile or get_active_model_profile()
        self.api_keys = _pkg.api_keys_for_profile(self.profile)
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
        cache_key = _pkg._llm_cache_key(self.profile, document_ir, group, fields, blocks)
        cached = _pkg._read_llm_result_cache(cache_key)
        if cached is not None:
            self.last_usage = _cache_hit_usage(cache_key)
            return cached
        payload = _pkg._responses_payload(
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
        _pkg._write_llm_result_cache(cache_key, result)
        return result

    def collect_evidence(
        self,
        *,
        document_context: DocumentContext,
        fields: list[FieldDefinition],
    ) -> dict[str, list[EvidenceCandidate]]:
        cache_key = _evidence_first_cache_key(self.profile, document_context, fields, stage="collect")
        cached = _pkg._read_evidence_candidate_cache(cache_key)
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
            _pkg._write_evidence_candidate_cache(cache_key, result)
            return result
        payload = _pkg._responses_evidence_first_payload(
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
        _pkg._write_evidence_candidate_cache(cache_key, result)
        return result

    # --- Async adapter methods ------------------------------------------------

    async def async_extract_group(
        self,
        *,
        document_ir: DocumentIR,
        group: FieldGroup,
        fields: list[FieldDefinition],
        blocks: list[DocumentIRBlock],
    ) -> list[ExtractionCandidate]:
        import asyncio
        from openai import AsyncOpenAI

        cache_key = _pkg._llm_cache_key(self.profile, document_ir, group, fields, blocks)
        cached = await asyncio.to_thread(_pkg._read_llm_result_cache, cache_key)
        if cached is not None:
            self.last_usage = _cache_hit_usage(cache_key)
            return cached
        payload = _pkg._responses_payload(
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
            client = AsyncOpenAI(**client_kwargs)
            try:
                response = await client.responses.create(**payload)
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
        await asyncio.to_thread(_pkg._write_llm_result_cache, cache_key, result)
        return result

    async def async_collect_evidence(
        self,
        *,
        document_context: DocumentContext,
        fields: list[FieldDefinition],
    ) -> dict[str, list[EvidenceCandidate]]:
        import asyncio
        from openai import AsyncOpenAI

        cache_key = _evidence_first_cache_key(self.profile, document_context, fields, stage="collect")
        cached = await asyncio.to_thread(_pkg._read_evidence_candidate_cache, cache_key)
        if cached is not None:
            self.last_usage = _cache_hit_usage(cache_key)
            return cached
        remote_policy = _remote_exposure_policy()
        if _requires_local_evidence_collection(remote_policy):
            from app.services.evidence_first import collect_local_evidence

            result = await asyncio.to_thread(collect_local_evidence, document_context, fields)
            self.last_usage = {
                "input_tokens": 0,
                "output_tokens": 0,
                "cached_input_tokens": 0,
                "cost_usd": 0.0,
                "remote_context_mode": _remote_context_mode(remote_policy),
                "remote_skipped_reason": "remote_full_context_disabled",
                **_cache_miss_usage(cache_key),
            }
            await asyncio.to_thread(_pkg._write_evidence_candidate_cache, cache_key, result)
            return result
        payload = _pkg._responses_evidence_first_payload(
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
            client = AsyncOpenAI(**client_kwargs)
            try:
                response = await client.responses.create(**payload)
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
        await asyncio.to_thread(_pkg._write_evidence_candidate_cache, cache_key, result)
        return result
