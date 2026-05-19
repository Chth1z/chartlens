"""Tests for async LLM adapter methods (S2-001).

Verifies:
1. Default async methods on SemanticExtractionProvider wrap sync in to_thread
2. OpenAIResponsesProvider.async_collect_evidence uses AsyncOpenAI
3. OpenAICompatibleChatProvider.async_collect_evidence uses AsyncOpenAI
4. ModelFallbackProvider.async_collect_evidence iterates the chain
5. run_provider_async utility dispatches correctly
6. Cache hits work in async path
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.models import (
    DocumentContext,
    DocumentIR,
    DocumentIRBlock,
    EvidenceCandidate,
    ExtractionCandidate,
    FieldDefinition,
    FieldGroup,
)
from app.services.llm_provider.types import (
    SemanticExtractionProvider,
    run_provider_async,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _ConcreteTestProvider(SemanticExtractionProvider):
    """Minimal concrete provider for testing the default async wrappers."""

    name = "test-provider"
    route = "test"

    def __init__(self):
        self.extract_group_called = False
        self.collect_evidence_called = False

    def extract_group(self, *, document_ir, group, fields, blocks):
        self.extract_group_called = True
        return [
            ExtractionCandidate(
                field_key=f.key,
                field_group_key=f.field_group_key,
                normalized_code="unknown",
                status="not_mentioned",
                confidence=0.0,
                evidence_type="no_evidence",
                reasoning_summary="test",
            )
            for f in fields
        ]

    def collect_evidence(self, *, document_context, fields):
        self.collect_evidence_called = True
        return {f.key: [] for f in fields}


def _make_field(key: str = "test_field") -> FieldDefinition:
    return FieldDefinition(
        key=key,
        label=key,
        field_group_key="test_group",
        export_header=key,
        extract_mode="rule_first",
        synonyms=[],
        negation_terms=[],
        excluded_sections=[],
        code_map={},
    )


def _make_group() -> FieldGroup:
    return FieldGroup(key="test_group", label="Test Group")


def _make_document_context() -> DocumentContext:
    return DocumentContext(
        document_id="test-doc",
        profile_id="test",
        source_filename="test.pdf",
        pages=[],
    )


def _make_document_ir() -> DocumentIR:
    return DocumentIR(
        document_id="test-doc",
        profile_id="test",
        source_filename="test.pdf",
        blocks=[],
    )


# ---------------------------------------------------------------------------
# 1. Default async methods wrap sync in to_thread
# ---------------------------------------------------------------------------


async def test_default_async_extract_group_wraps_sync():
    provider = _ConcreteTestProvider()
    fields = [_make_field()]
    result = await provider.async_extract_group(
        document_ir=_make_document_ir(),
        group=_make_group(),
        fields=fields,
        blocks=[],
    )
    assert provider.extract_group_called
    assert len(result) == 1
    assert result[0].field_key == "test_field"


async def test_default_async_collect_evidence_wraps_sync():
    provider = _ConcreteTestProvider()
    fields = [_make_field()]
    result = await provider.async_collect_evidence(
        document_context=_make_document_context(),
        fields=fields,
    )
    assert provider.collect_evidence_called
    assert "test_field" in result


# ---------------------------------------------------------------------------
# 2. OpenAIResponsesProvider.async_collect_evidence uses AsyncOpenAI
# ---------------------------------------------------------------------------


async def test_openai_responses_async_collect_evidence_uses_async_client(monkeypatch):
    """Verify that async_collect_evidence instantiates AsyncOpenAI."""
    monkeypatch.setattr(
        "app.services.llm_provider.adapters.api_keys_for_profile",
        lambda profile: ["test-key"],
    )
    monkeypatch.setattr(
        "app.services.llm_provider.adapters.openai_responses._remote_exposure_policy",
        lambda: SimpleNamespace(allow_full_context=True),
    )
    monkeypatch.setattr(
        "app.services.llm_provider.adapters.openai_responses._requires_local_evidence_collection",
        lambda policy: False,
    )

    # Mock cache miss
    monkeypatch.setattr(
        "app.services.llm_provider.adapters._read_evidence_candidate_cache",
        lambda key: None,
    )
    monkeypatch.setattr(
        "app.services.llm_provider.adapters._write_evidence_candidate_cache",
        lambda key, result: None,
    )

    # Mock payload builder
    monkeypatch.setattr(
        "app.services.llm_provider.adapters._responses_evidence_first_payload",
        lambda **kwargs: {"model": "test", "input": "test"},
    )

    # Track AsyncOpenAI usage
    async_client_used = []

    class FakeAsyncResponses:
        async def create(self, **kwargs):
            return SimpleNamespace(
                output_text='{"evidence_candidates": []}',
                usage=SimpleNamespace(
                    input_tokens=10,
                    output_tokens=5,
                    input_tokens_details=None,
                    prompt_tokens_details=None,
                ),
            )

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            async_client_used.append(kwargs)
            self.responses = FakeAsyncResponses()

    monkeypatch.setattr(
        "openai.AsyncOpenAI", FakeAsyncOpenAI,
    )

    from app.services.llm_provider.adapters.openai_responses import OpenAIResponsesProvider

    profile = SimpleNamespace(
        provider="openai_responses",
        provider_id="openai",
        profile_id="openai_responses_profile",
        model="gpt-4o",
        base_url=None,
        api_key_env="EYEX_OPENAI_API_KEY",
        api_key_value=None,
        auth_env_vars=["EYEX_OPENAI_API_KEY"],
        auth_optional=False,
        model_ref=None,
        api=None,
        fallbacks=[],
    )
    provider = OpenAIResponsesProvider(profile=profile)
    fields = [_make_field()]

    result = await provider.async_collect_evidence(
        document_context=_make_document_context(),
        fields=fields,
    )

    assert len(async_client_used) == 1
    assert async_client_used[0]["api_key"] == "test-key"
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# 3. OpenAICompatibleChatProvider.async_collect_evidence uses AsyncOpenAI
# ---------------------------------------------------------------------------


async def test_openai_compatible_async_collect_evidence_uses_async_client(monkeypatch):
    """Verify that async_collect_evidence instantiates AsyncOpenAI."""
    monkeypatch.setattr(
        "app.services.llm_provider.adapters.api_keys_for_profile",
        lambda profile: ["test-key"],
    )
    monkeypatch.setattr(
        "app.services.llm_provider.adapters.openai_compatible._remote_exposure_policy",
        lambda: SimpleNamespace(allow_full_context=True),
    )
    monkeypatch.setattr(
        "app.services.llm_provider.adapters.openai_compatible._requires_local_evidence_collection",
        lambda policy: False,
    )

    # Mock cache miss
    monkeypatch.setattr(
        "app.services.llm_provider.adapters._read_evidence_candidate_cache",
        lambda key: None,
    )
    monkeypatch.setattr(
        "app.services.llm_provider.adapters._write_evidence_candidate_cache",
        lambda key, result: None,
    )

    # Mock payload builder
    monkeypatch.setattr(
        "app.services.llm_provider.adapters.openai_compatible._chat_completions_evidence_first_payload",
        lambda **kwargs: {"model": "test", "messages": []},
    )

    # Track AsyncOpenAI usage
    async_client_used = []

    class FakeAsyncChatCompletions:
        async def create(self, **kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"test_field": []}'))],
                usage=SimpleNamespace(
                    prompt_tokens=10,
                    completion_tokens=5,
                    prompt_tokens_details=None,
                    prompt_cache_hit_tokens=0,
                ),
            )

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            async_client_used.append(kwargs)
            self.chat = SimpleNamespace(completions=FakeAsyncChatCompletions())

    monkeypatch.setattr(
        "openai.AsyncOpenAI", FakeAsyncOpenAI,
    )

    from app.services.llm_provider.adapters.openai_compatible import OpenAICompatibleChatProvider

    profile = SimpleNamespace(
        provider="openai_compatible",
        provider_id="deepseek",
        profile_id="deepseek_chat_profile",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_key_env="DEEPSEEK_API_KEY",
        api_key_value=None,
        auth_env_vars=["DEEPSEEK_API_KEY"],
        auth_optional=False,
        model_ref=None,
        api=None,
        fallbacks=[],
        structured_output_mode="json_object",
    )
    provider = OpenAICompatibleChatProvider(profile=profile)
    fields = [_make_field()]

    result = await provider.async_collect_evidence(
        document_context=_make_document_context(),
        fields=fields,
    )

    assert len(async_client_used) == 1
    assert async_client_used[0]["api_key"] == "test-key"
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# 4. ModelFallbackProvider.async_collect_evidence iterates chain
# ---------------------------------------------------------------------------


async def test_fallback_async_collect_evidence_iterates_chain(monkeypatch):
    """ModelFallbackProvider.async_collect_evidence should try each
    provider in the chain and fall back on failure."""

    call_order = []

    class FailingProvider(SemanticExtractionProvider):
        name = "failing"
        route = "test"

        def extract_group(self, **kwargs):
            raise NotImplementedError

        def collect_evidence(self, **kwargs):
            raise RuntimeError("sync should not be called")

        async def async_collect_evidence(self, *, document_context, fields):
            call_order.append("failing")
            raise RuntimeError("simulated failure")

    class SucceedingProvider(SemanticExtractionProvider):
        name = "succeeding"
        route = "test_success"

        def extract_group(self, **kwargs):
            raise NotImplementedError

        def collect_evidence(self, **kwargs):
            raise RuntimeError("sync should not be called")

        async def async_collect_evidence(self, *, document_context, fields):
            call_order.append("succeeding")
            self.last_usage = {"input_tokens": 5, "output_tokens": 3}
            return {f.key: [] for f in fields}

    # Patch _provider_for_profile to return our test providers
    providers_iter = iter([FailingProvider(), SucceedingProvider()])

    monkeypatch.setattr(
        "app.services.llm_provider.fallback._provider_for_profile",
        lambda profile: next(providers_iter),
    )
    # Patch _is_failover_worthy to allow failover
    monkeypatch.setattr(
        "app.services.llm_provider.fallback._is_failover_worthy",
        lambda exc: True,
    )

    from app.services.llm_provider.fallback import ModelFallbackProvider

    profiles = [
        SimpleNamespace(profile_id="p1", model="m1", model_ref=None, provider_id="p1"),
        SimpleNamespace(profile_id="p2", model="m2", model_ref=None, provider_id="p2"),
    ]
    fallback = ModelFallbackProvider(profiles)
    fields = [_make_field()]

    result = await fallback.async_collect_evidence(
        document_context=_make_document_context(),
        fields=fields,
    )

    assert call_order == ["failing", "succeeding"]
    assert "test_field" in result
    assert fallback.name == "succeeding"


# ---------------------------------------------------------------------------
# 5. run_provider_async utility
# ---------------------------------------------------------------------------


async def test_run_provider_async_calls_async_method_when_available():
    """run_provider_async should prefer the async_ prefixed method."""
    provider = _ConcreteTestProvider()
    fields = [_make_field()]

    result = await run_provider_async(
        provider,
        "collect_evidence",
        document_context=_make_document_context(),
        fields=fields,
    )

    # The default async method delegates to sync via to_thread
    assert provider.collect_evidence_called
    assert "test_field" in result


async def test_run_provider_async_falls_back_to_sync_via_to_thread():
    """When no async_ method exists, run_provider_async wraps sync in to_thread."""

    class NoAsyncProvider(SemanticExtractionProvider):
        name = "no-async"
        route = "test"

        def extract_group(self, **kwargs):
            return []

        def collect_evidence(self, *, document_context, fields):
            return {"called": True}

    provider = NoAsyncProvider()
    # Patch the instance to remove the inherited async method
    provider.async_collect_evidence = None  # type: ignore[assignment]

    result = await run_provider_async(
        provider,
        "collect_evidence",
        document_context=_make_document_context(),
        fields=[_make_field()],
    )

    assert result == {"called": True}


# ---------------------------------------------------------------------------
# 6. Cache hits work in async path
# ---------------------------------------------------------------------------


async def test_openai_responses_async_collect_evidence_cache_hit(monkeypatch):
    """When cache has a hit, async_collect_evidence returns it without calling the API."""
    monkeypatch.setattr(
        "app.services.llm_provider.adapters.api_keys_for_profile",
        lambda profile: ["test-key"],
    )

    cached_result = {"test_field": []}
    monkeypatch.setattr(
        "app.services.llm_provider.adapters._read_evidence_candidate_cache",
        lambda key: cached_result,
    )

    from app.services.llm_provider.adapters.openai_responses import OpenAIResponsesProvider

    profile = SimpleNamespace(
        provider="openai_responses",
        provider_id="openai",
        profile_id="openai_responses_profile",
        model="gpt-4o",
        base_url=None,
        api_key_env="EYEX_OPENAI_API_KEY",
        api_key_value=None,
        auth_env_vars=["EYEX_OPENAI_API_KEY"],
        auth_optional=False,
        model_ref=None,
        api=None,
        fallbacks=[],
    )
    provider = OpenAIResponsesProvider(profile=profile)
    fields = [_make_field()]

    result = await provider.async_collect_evidence(
        document_context=_make_document_context(),
        fields=fields,
    )

    assert result is cached_result


async def test_openai_compatible_async_extract_group_cache_hit(monkeypatch):
    """When cache has a hit, async_extract_group returns it without calling the API."""
    monkeypatch.setattr(
        "app.services.llm_provider.adapters.api_keys_for_profile",
        lambda profile: ["test-key"],
    )

    cached_result = [
        ExtractionCandidate(
            field_key="test_field",
            field_group_key="test_group",
            normalized_code="unknown",
            status="not_mentioned",
            confidence=0.0,
            evidence_type="no_evidence",
            reasoning_summary="cached",
        )
    ]
    monkeypatch.setattr(
        "app.services.llm_provider.adapters._read_llm_result_cache",
        lambda key: cached_result,
    )

    from app.services.llm_provider.adapters.openai_compatible import OpenAICompatibleChatProvider

    profile = SimpleNamespace(
        provider="openai_compatible",
        provider_id="deepseek",
        profile_id="deepseek_chat_profile",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_key_env="DEEPSEEK_API_KEY",
        api_key_value=None,
        auth_env_vars=["DEEPSEEK_API_KEY"],
        auth_optional=False,
        model_ref=None,
        api=None,
        fallbacks=[],
        structured_output_mode="json_object",
    )
    provider = OpenAICompatibleChatProvider(profile=profile)
    fields = [_make_field()]

    result = await provider.async_extract_group(
        document_ir=_make_document_ir(),
        group=_make_group(),
        fields=fields,
        blocks=[],
    )

    assert result is cached_result
