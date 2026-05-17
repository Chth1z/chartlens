"""Provider registry for the LLM provider router.

Replaces the if/elif chain in `fallback._provider_for_profile` with a
data-driven dispatch table. Adding a new provider kind no longer means
editing two places (the catalog YAML and the if/elif); it means adding
one entry to `_PROVIDER_REGISTRY`.

Design rationale (E1-011 Phase 3, 2026-05-18):

- Every concrete `SemanticExtractionProvider` adapter is registered
  here, keyed by the `provider` literal in `ModelProfile`. The literal
  must match the values declared in `config/model_providers/mainstream.yaml`.
- Each registry entry declares which `settings.llm_mode` values are
  acceptable for that provider. This preserves the existing rule that
  `openai_compatible` adapters can run in `local` mode (because they
  accept `base_url` overrides like Ollama or LM Studio), while online-only
  providers are gated to `auto` / `online`.
- The `disabled` provider returns `ConservativeLocalProvider` regardless
  of mode. This is the off-switch that `build_semantic_provider` honors
  before constructing a router chain.

The contract test in `backend/tests/test_provider_contracts.py` enforces
that the registry covers every `provider` literal declared in the
catalog YAML; a new provider kind without a registry entry will fail
the test before runtime.
"""
from __future__ import annotations

from typing import Callable, Mapping

from app.core.settings import settings
from app.services.llm_provider.adapters import (
    AnthropicMessagesProvider,
    GoogleGeminiProvider,
    OpenAICompatibleChatProvider,
    OpenAIResponsesProvider,
)
from app.services.llm_provider.local_extraction import ConservativeLocalProvider
from app.services.llm_provider.types import SemanticExtractionProvider
from app.services.llm_provider.utils import _model_ref


# llm_mode values that allow remote calls. `auto` and `online` map to
# any cloud adapter; `local` only allows openai_compatible because that
# adapter accepts a base_url override pointing at a local model server
# (Ollama, LM Studio, llama.cpp). `disabled` falls through to the local
# rule provider regardless of which adapter the profile names.
_REMOTE_MODES = {"auto", "online"}
_LOCAL_OK_MODES = _REMOTE_MODES | {"local"}


# Each registry entry is (adapter factory, allowed llm_mode values).
# The factory must accept a single `profile` argument and return a
# constructed `SemanticExtractionProvider`.
_PROVIDER_REGISTRY: Mapping[
    str,
    tuple[Callable[[object], SemanticExtractionProvider], frozenset[str]],
] = {
    "openai_responses": (OpenAIResponsesProvider, frozenset(_REMOTE_MODES)),
    "openai_compatible": (OpenAICompatibleChatProvider, frozenset(_LOCAL_OK_MODES)),
    "anthropic_messages": (AnthropicMessagesProvider, frozenset(_REMOTE_MODES)),
    "google_gemini": (GoogleGeminiProvider, frozenset(_REMOTE_MODES)),
}


def registered_provider_kinds() -> frozenset[str]:
    """Return the set of provider literals the registry knows about.

    The contract test compares this set against the catalog YAML to
    detect drift (a YAML entry without an adapter, or an adapter without
    a YAML entry).
    """
    return frozenset(_PROVIDER_REGISTRY)


def provider_for_profile(profile) -> SemanticExtractionProvider:
    """Construct the adapter for the given profile, honoring llm_mode.

    `disabled` profiles always return ConservativeLocalProvider. Any
    other profile whose `provider` is not in the registry, or whose
    `provider` is in the registry but not allowed in the current
    llm_mode, raises RuntimeError. The error names the profile so the
    caller can surface it in the durable observability ledger.
    """
    if getattr(profile, "provider", None) == "disabled":
        return ConservativeLocalProvider()

    entry = _PROVIDER_REGISTRY.get(profile.provider)
    if entry is None:
        raise RuntimeError(
            f"Unknown provider kind: {profile.provider!r} for {_model_ref(profile)}"
        )

    factory, allowed_modes = entry
    if settings.llm_mode not in allowed_modes:
        raise RuntimeError(
            f"Model profile is not runnable in current mode: {_model_ref(profile)}"
        )
    return factory(profile)
