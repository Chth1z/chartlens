"""Async method implementations for OpenAICompatibleChatProvider.

This module contains the async versions of the chat-completions request
loop, extract_group, and collect_evidence. They are defined as a mixin
class that OpenAICompatibleChatProvider inherits from, keeping the main
adapter file focused on the sync contract methods.

Extracted from openai_compatible.py for single-file complexity governance.
"""
from __future__ import annotations
from typing import Any

from app.core.settings import settings
from app.domain.models import (
    DocumentContext, DocumentIR, DocumentIRBlock,
    EvidenceCandidate, ExtractionCandidate, FieldDefinition, FieldGroup,
)
from app.services.safe_errors import safe_error_message
from app.services.llm_provider import adapters as _pkg
from ..utils import (
    _api_keys_for_attempts, _chat_response_content,
    _is_rate_limit_or_timeout, _mark_api_key_cooldown,
    _should_try_next_openai_compatible_base_url,
    _should_try_next_openai_compatible_response,
)
from ..cache import _cache_hit_usage, _cache_miss_usage, _evidence_first_cache_key
from ..parsing import _candidates_from_text, _evidence_candidates_from_text
from ..types import local_collect_evidence_fallback, local_evidence_fallback_usage
from ._structured_output import (
    _is_structured_output_capability_error,
    _StructuredOutputCapabilityError,
)


class _OpenAICompatibleAsyncMixin:
    """Mixin providing native async implementations for the OpenAI-
    compatible chat adapter. Requires the host class to define:
      - self.profile
      - self.api_keys
      - self.base_urls
      - self.base_url
      - self.model
      - self.last_usage
      - self._modes_to_try()
      - self._chat_evidence_local_fallback(...)
    """

    async def _async_run_chat_request(self, payload: dict[str, Any]) -> tuple[Any, str]:
        """Async version of _run_chat_request using AsyncOpenAI."""
        from openai import AsyncOpenAI

        last_error: Exception | None = None
        for api_key in _api_keys_for_attempts(self.profile, self.api_keys):  # type: ignore[attr-defined]
            response = None
            content: str | None = None
            for index, base_url in enumerate(self.base_urls):  # type: ignore[attr-defined]
                client = AsyncOpenAI(
                    api_key=api_key, base_url=base_url, timeout=settings.openai_timeout_seconds
                )
                try:
                    response = await client.chat.completions.create(**payload)
                    content = _chat_response_content(response)
                    has_next_base_url = index < len(self.base_urls) - 1  # type: ignore[attr-defined]
                    if has_next_base_url and _should_try_next_openai_compatible_response(content):
                        response = None
                        content = None
                        continue
                    self.base_url = base_url  # type: ignore[attr-defined]
                    return response, content or ""
                except Exception as exc:
                    last_error = exc
                    if _is_structured_output_capability_error(exc):
                        raise _StructuredOutputCapabilityError(exc) from exc
                    has_next_base_url = index < len(self.base_urls) - 1  # type: ignore[attr-defined]
                    if has_next_base_url and _should_try_next_openai_compatible_base_url(exc):
                        continue
                    if not _is_rate_limit_or_timeout(exc):
                        raise
                    _mark_api_key_cooldown(self.profile, api_key, exc)  # type: ignore[attr-defined]
                    break
        raise last_error or RuntimeError("OpenAI-compatible request failed")

    async def async_extract_group(
        self,
        *,
        document_ir: DocumentIR,
        group: FieldGroup,
        fields: list[FieldDefinition],
        blocks: list[DocumentIRBlock],
    ) -> list[ExtractionCandidate]:
        import asyncio

        cache_key = _pkg._llm_cache_key(self.profile, document_ir, group, fields, blocks)  # type: ignore[attr-defined]
        cached = await asyncio.to_thread(_pkg._read_llm_result_cache, cache_key)
        if cached is not None:
            self.last_usage = _cache_hit_usage(cache_key)  # type: ignore[attr-defined]
            return cached

        modes = self._modes_to_try()  # type: ignore[attr-defined]
        initial_mode = modes[0]
        capability_error: Exception | None = None
        response = None
        content: str = ""
        used_mode = initial_mode
        downgrade_reason: str | None = None

        for attempt_index, mode in enumerate(modes):
            payload = _pkg._chat_completions_payload(
                document_ir=document_ir,
                group=group,
                fields=fields,
                blocks=blocks,
                model=self.model,  # type: ignore[attr-defined]
                profile=self.profile,  # type: ignore[attr-defined]
                structured_output_mode=mode,
            )
            try:
                response, content = await self._async_run_chat_request(payload)
            except _StructuredOutputCapabilityError as exc:
                capability_error = exc.original
                if attempt_index < len(modes) - 1:
                    continue
                raise capability_error
            used_mode = mode
            if attempt_index > 0 and capability_error is not None:
                downgrade_reason = (
                    f"{initial_mode} -> {mode}: {safe_error_message(capability_error)}"
                )
            break

        usage = getattr(response, "usage", None)
        self.last_usage = {  # type: ignore[attr-defined]
            "input_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "output_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            "cached_input_tokens": 0,
            "cost_usd": 0.0,
            "structured_output_mode": used_mode,
            **_cache_miss_usage(cache_key),
        }
        if downgrade_reason:
            self.last_usage["structured_output_downgrade"] = downgrade_reason  # type: ignore[attr-defined]
        if not content:
            raise ValueError("OpenAI-compatible response did not contain message content")
        result = _candidates_from_text(content)
        await asyncio.to_thread(_pkg._write_llm_result_cache, cache_key, result)
        return result

    async def async_collect_evidence(
        self,
        *,
        document_context: DocumentContext,
        fields: list[FieldDefinition],
    ) -> dict[str, list[EvidenceCandidate]]:
        """Async version of collect_evidence using AsyncOpenAI."""
        import asyncio
        # Late-bind payload/policy helpers so monkeypatch on the host
        # module (openai_compatible) is visible to tests.
        from app.services.llm_provider.adapters import openai_compatible as _host
        _remote_exposure_policy = _host._remote_exposure_policy
        _requires_local_evidence_collection = _host._requires_local_evidence_collection
        _remote_context_mode = _host._remote_context_mode
        _chat_completions_evidence_first_payload = _host._chat_completions_evidence_first_payload

        cache_key = _evidence_first_cache_key(self.profile, document_context, fields, stage="collect")  # type: ignore[attr-defined]
        cached = await asyncio.to_thread(_pkg._read_evidence_candidate_cache, cache_key)
        if cached is not None:
            self.last_usage = _cache_hit_usage(cache_key)  # type: ignore[attr-defined]
            return cached

        remote_policy = _remote_exposure_policy()
        if _requires_local_evidence_collection(remote_policy):
            result = await asyncio.to_thread(local_collect_evidence_fallback, document_context, fields)
            self.last_usage = {  # type: ignore[attr-defined]
                **local_evidence_fallback_usage(),
                "remote_context_mode": _remote_context_mode(remote_policy),
                "remote_skipped_reason": "remote_full_context_disabled",
                **_cache_miss_usage(cache_key),
            }
            await asyncio.to_thread(_pkg._write_evidence_candidate_cache, cache_key, result)
            return result

        modes = self._modes_to_try()  # type: ignore[attr-defined]
        initial_mode = modes[0]
        capability_error: Exception | None = None
        response = None
        content: str = ""
        used_mode = initial_mode
        downgrade_reason: str | None = None

        for attempt_index, mode in enumerate(modes):
            try:
                payload = _chat_completions_evidence_first_payload(
                    document_context=document_context,
                    fields=fields,
                    model=self.model,  # type: ignore[attr-defined]
                    profile=self.profile,  # type: ignore[attr-defined]
                    structured_output_mode=mode,
                )
            except ValueError as exc:
                return self._chat_evidence_local_fallback(  # type: ignore[attr-defined]
                    document_context=document_context,
                    fields=fields,
                    cache_key=cache_key,
                    failure=capability_error or exc,
                    failure_reason="structured_output_capability_exhausted",
                )

            try:
                response, content = await self._async_run_chat_request(payload)
            except _StructuredOutputCapabilityError as exc:
                capability_error = exc.original
                if attempt_index < len(modes) - 1:
                    continue
                return self._chat_evidence_local_fallback(  # type: ignore[attr-defined]
                    document_context=document_context,
                    fields=fields,
                    cache_key=cache_key,
                    failure=capability_error,
                    failure_reason="structured_output_capability_exhausted",
                )
            except Exception as exc:
                failure_reason = (
                    "no_response" if _is_rate_limit_or_timeout(exc) else "permanent_error"
                )
                return self._chat_evidence_local_fallback(  # type: ignore[attr-defined]
                    document_context=document_context,
                    fields=fields,
                    cache_key=cache_key,
                    failure=exc,
                    failure_reason=failure_reason,
                )

            used_mode = mode
            if attempt_index > 0 and capability_error is not None:
                downgrade_reason = (
                    f"{initial_mode} -> {mode}: {safe_error_message(capability_error)}"
                )
            break

        if response is None or not content:
            return self._chat_evidence_local_fallback(  # type: ignore[attr-defined]
                document_context=document_context,
                fields=fields,
                cache_key=cache_key,
                failure=capability_error,
                failure_reason="no_response",
            )

        try:
            result = _evidence_candidates_from_text(content)
        except Exception as exc:
            return self._chat_evidence_local_fallback(  # type: ignore[attr-defined]
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
            if not prompt_cache_hit_tokens:
                prompt_cache_hit_tokens = int(getattr(usage, "prompt_cache_hit_tokens", 0) or 0)

        self.last_usage = {  # type: ignore[attr-defined]
            "input_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "output_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            "cached_input_tokens": prompt_cache_hit_tokens,
            "cost_usd": 0.0,
            "evidence_collection_method": "remote_chat_completions",
            "structured_output_mode": used_mode,
            **_cache_miss_usage(cache_key),
        }
        if downgrade_reason:
            self.last_usage["structured_output_downgrade"] = downgrade_reason  # type: ignore[attr-defined]
        await asyncio.to_thread(_pkg._write_evidence_candidate_cache, cache_key, result)
        return result
