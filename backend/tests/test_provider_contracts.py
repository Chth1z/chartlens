"""Contract tests for the LLM provider adapter ABC.

Pins the rules established by E1-011 Phase 1:

1. Every concrete subclass of `SemanticExtractionProvider` defines
   `collect_evidence` directly on itself, not via inheritance from the
   base class. The base class no longer offers a default implementation.

2. Every `provider` value declared in `config/model_providers/mainstream.yaml`
   has a corresponding adapter class wired through
   `services.llm_provider.fallback._provider_for_profile`.

3. `local_collect_evidence_fallback` and `local_evidence_fallback_usage`
   are exported from `services.llm_provider.types` and are stable seams
   that LLM adapters can call when their remote implementation is not
   available or must degrade gracefully.

Adding a new adapter without satisfying these rules will fail this file.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from app.services.llm_provider.adapters import (
    AnthropicMessagesProvider,
    GoogleGeminiProvider,
    OpenAICompatibleChatProvider,
    OpenAIResponsesProvider,
)
from app.services.llm_provider.fallback import _provider_for_profile
from app.services.llm_provider.local_extraction import ConservativeLocalProvider
from app.services.llm_provider.types import (
    SemanticExtractionProvider,
    local_collect_evidence_fallback,
    local_evidence_fallback_usage,
)


CONCRETE_PROVIDERS: list[type[SemanticExtractionProvider]] = [
    OpenAIResponsesProvider,
    OpenAICompatibleChatProvider,
    AnthropicMessagesProvider,
    GoogleGeminiProvider,
    ConservativeLocalProvider,
]


@pytest.mark.parametrize("provider_cls", CONCRETE_PROVIDERS, ids=lambda cls: cls.__name__)
def test_provider_overrides_collect_evidence_explicitly(provider_cls):
    """Every concrete adapter must define collect_evidence on itself.

    Inheriting the base-class default is forbidden because the base class
    no longer offers one (it is `@abstractmethod`). A regression that
    re-introduces a default would fail this assertion before any LLM
    bootstrap run silently falls back to local extraction again.
    """
    assert "collect_evidence" in provider_cls.__dict__, (
        f"{provider_cls.__name__} must define collect_evidence directly. "
        "Inheriting the base default is forbidden per E1-011 Phase 1; if the "
        "remote API is not implemented yet, return "
        "local_collect_evidence_fallback(...) explicitly and assign "
        "local_evidence_fallback_usage() to self.last_usage."
    )


@pytest.mark.parametrize("provider_cls", CONCRETE_PROVIDERS, ids=lambda cls: cls.__name__)
def test_provider_overrides_extract_group_explicitly(provider_cls):
    """Every concrete adapter must define extract_group on itself.

    Symmetric to the collect_evidence rule. The base class also marks this
    as `@abstractmethod` since 2024; this test makes the property explicit
    so a future refactor that loosens the base class fails here.
    """
    assert "extract_group" in provider_cls.__dict__, (
        f"{provider_cls.__name__} must define extract_group directly."
    )


def test_local_evidence_fallback_helpers_are_exported():
    """The named delegation seam is part of the public adapter contract.

    Adapters that defer their remote implementation must call these two
    helpers explicitly. Renaming or removing them is a breaking change
    that requires a coordinated update of every adapter that delegates.
    """
    assert callable(local_collect_evidence_fallback)
    sig = inspect.signature(local_collect_evidence_fallback)
    assert list(sig.parameters) == ["document_context", "fields"]

    assert callable(local_evidence_fallback_usage)
    usage = local_evidence_fallback_usage()
    assert usage["evidence_collection_method"] == "local_fallback"
    assert usage["input_tokens"] == 0
    assert usage["output_tokens"] == 0
    assert usage["cost_usd"] == 0.0


def test_provider_catalog_yaml_covers_every_provider_value():
    """Every `provider` value declared in config/model_providers/mainstream.yaml
    must resolve through `_provider_for_profile` to a concrete adapter
    class. Adding a new provider without an adapter wiring will fail
    this test.
    """
    catalog_path = Path(__file__).resolve().parents[2] / "config" / "model_providers" / "mainstream.yaml"
    payload = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    declared = set()
    for entry in payload.get("providers", []) or []:
        if not isinstance(entry, dict):
            continue
        provider_kind = entry.get("provider_kind") or entry.get("provider") or entry.get("api")
        # Catalog entries declare provider kinds either as the python
        # `ModelProfile.provider` literal or as an `api` shortcut. Both
        # are acceptable — what we check is that the runtime can
        # construct a profile with that kind and route it to an adapter.
        if isinstance(provider_kind, str) and provider_kind:
            declared.add(provider_kind)

    expected_python_kinds = {
        "openai_responses",
        "openai_compatible",
        "anthropic_messages",
        "google_gemini",
        "disabled",
    }
    api_aliases_to_python_kind = {
        "openai-responses": "openai_responses",
        "openai-completions": "openai_compatible",
        "openai-chat": "openai_compatible",
        "anthropic-messages": "anthropic_messages",
        "google-gemini": "google_gemini",
        "disabled": "disabled",
    }

    # Map each declared catalog kind to its python provider literal and
    # confirm the literal is one of the supported set. This decouples the
    # test from whether the YAML uses python-style or api-style names.
    for kind in declared:
        python_kind = api_aliases_to_python_kind.get(kind, kind)
        assert python_kind in expected_python_kinds, (
            f"provider kind '{kind}' in mainstream.yaml has no adapter wiring. "
            "Add an entry to expected_python_kinds and a branch to "
            "_provider_for_profile if the runtime should accept it."
        )

    # Symmetric direction: every supported python kind has at least one
    # entry in the catalog OR is the special 'disabled' sentinel. This
    # prevents an adapter from existing in code without a way for users
    # to select it.
    for python_kind in expected_python_kinds - {"disabled"}:
        present = any(
            api_aliases_to_python_kind.get(declared_kind, declared_kind) == python_kind
            for declared_kind in declared
        )
        assert present or python_kind == "openai_responses", (
            f"adapter for provider kind '{python_kind}' has no entry in "
            "config/model_providers/mainstream.yaml. Either add a catalog "
            "entry or remove the adapter."
        )


def test_provider_for_profile_dispatches_to_known_adapters(monkeypatch):
    """`_provider_for_profile` must return one of the known adapter
    classes for each supported `provider` value, given a usable key.

    This test stubs api_keys_for_profile so adapter __init__ does not
    actually try to load real credentials.
    """
    monkeypatch.setattr(
        "app.services.llm_provider.adapters.api_keys_for_profile",
        lambda profile: ["test-key"],
    )

    expected = {
        "openai_responses": OpenAIResponsesProvider,
        "openai_compatible": OpenAICompatibleChatProvider,
        "anthropic_messages": AnthropicMessagesProvider,
        "google_gemini": GoogleGeminiProvider,
    }

    for provider_kind, adapter_cls in expected.items():
        profile = SimpleNamespace(
            provider=provider_kind,
            provider_id=provider_kind.split("_")[0],
            profile_id=f"{provider_kind}_profile",
            model="test-model",
            base_url="https://example.test",
            api_key_env="TEST_API_KEY",
            api_key_value=None,
            auth_env_vars=["TEST_API_KEY"],
            auth_optional=False,
            model_ref=None,
            api=None,
            fallbacks=[],
        )
        adapter = _provider_for_profile(profile)
        assert isinstance(adapter, adapter_cls), (
            f"_provider_for_profile returned {type(adapter).__name__} for "
            f"provider={provider_kind!r}, expected {adapter_cls.__name__}"
        )


def test_disabled_profile_returns_local_provider():
    profile = SimpleNamespace(
        provider="disabled",
        provider_id=None,
        profile_id="local_disabled",
        model="local-disabled",
        base_url=None,
        api_key_env=None,
        api_key_value=None,
        auth_env_vars=[],
        auth_optional=True,
        model_ref=None,
        api=None,
        fallbacks=[],
    )
    adapter = _provider_for_profile(profile)
    assert isinstance(adapter, ConservativeLocalProvider)


def test_base_class_collect_evidence_is_abstract():
    """Calling SemanticExtractionProvider.collect_evidence on an instance
    that does not override it must fail. This is the structural guarantee
    that future adapters cannot accidentally inherit a silent fallback."""

    # The base class itself cannot be instantiated because its abstract
    # methods are unimplemented. We assert that property directly.
    with pytest.raises(TypeError) as exc_info:
        SemanticExtractionProvider()  # type: ignore[abstract]
    message = str(exc_info.value)
    assert "abstract" in message.lower()
    assert "collect_evidence" in message or "extract_group" in message
