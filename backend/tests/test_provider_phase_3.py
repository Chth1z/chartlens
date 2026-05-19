"""Contract tests for E1-011 Phase 3.

Pins:

1. The Anthropic and Gemini evidence-first payload shapes are stable and
   place the byte-stable system prompt + JSON schema descriptor before
   the per-case content. This is the prerequisite for prompt-cache hits
   (E1-002) and protects DeepSeek-style cost amortization for adapters
   that support context caching.

2. `AnthropicMessagesProvider.collect_evidence` and
   `GoogleGeminiProvider.collect_evidence` are now real implementations,
   not local-fallback shims. They explicitly call their respective
   upstream APIs through `httpx.Client.post`.

3. `services/llm_provider/registry.py` is the single dispatch source.
   Every provider literal in `config/model_providers/mainstream.yaml`
   resolves through the registry, and adding a new provider literal
   without registering it fails the coverage test.

A regression that re-introduces the explicit-delegation shim, or that
breaks the cacheable-prefix discipline, will fail this file before it
can silently degrade the LLM baseline.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from app.domain.models import DocumentContext, RemoteExposurePolicy
from app.services.llm_provider.adapters import (
    AnthropicMessagesProvider,
    GoogleGeminiProvider,
    OpenAICompatibleChatProvider,
)
from app.services.llm_provider.payloads import (
    _anthropic_evidence_first_payload,
    _evidence_first_system_prompt,
    _gemini_evidence_first_payload,
    _gemini_response_schema,
    set_runtime_exposure_policy_override,
)
from app.services.llm_provider.parsing import _evidence_candidate_response_schema
from app.services.llm_provider.registry import (
    provider_for_profile,
    registered_provider_kinds,
)
from app.services.llm_provider.types import local_collect_evidence_fallback


def _empty_context() -> DocumentContext:
    return DocumentContext(
        document_id="phase-3-test",
        profile_id="medical_inpatient_zh",
        source_filename="phase-3-test.txt",
        pages=[],
        metadata={"context_version": "document-context-v1"},
    )


def _profile(provider_kind: str, *, model: str = "test-model") -> SimpleNamespace:
    return SimpleNamespace(
        provider=provider_kind,
        provider_id=provider_kind.split("_")[0],
        profile_id=f"{provider_kind}_profile",
        model=model,
        base_url="https://example.test",
        api_key_env="TEST_API_KEY",
        api_key_value=None,
        auth_env_vars=["TEST_API_KEY"],
        auth_optional=False,
        model_ref=None,
        api=None,
        fallbacks=[],
        max_output_tokens=1024,
        temperature=0.0,
        prompt_cache_key="test-prefix",
        reasoning_effort=None,
        input=[],
    )


# ---------------------------------------------------------------------------
# Payload shape contracts
# ---------------------------------------------------------------------------


def test_anthropic_evidence_first_payload_has_cacheable_prefix():
    """The Anthropic system field carries the byte-stable prompt prefix.

    Anthropic's prompt caching reads from the `system` field; mixing
    per-case content into `system` would invalidate every cache hit.
    """
    profile = _profile("anthropic_messages")
    payload = _anthropic_evidence_first_payload(
        document_context=_empty_context(),
        fields=[],
        model="claude-test",
        profile=profile,
    )
    assert payload["model"] == "claude-test"
    assert payload["max_tokens"] == profile.max_output_tokens
    assert payload["temperature"] == profile.temperature
    # System carries the system prompt + schema descriptor.
    system_text = payload["system"]
    assert "证据绑定要求" in system_text
    assert "evidence_candidates" in system_text  # schema descriptor leaked in
    # Per-case content is in messages, not system.
    assert payload["messages"][0]["role"] == "user"
    user_content = payload["messages"][0]["content"]
    assert isinstance(user_content, str)
    parsed = json.loads(user_content)
    assert parsed["task"] == "collect_field_evidence_candidates"


def test_anthropic_evidence_first_payload_is_byte_stable_across_calls():
    """Two calls with identical inputs produce identical bytes.

    Required for any future adoption of Anthropic prompt caching. A drift
    here breaks the cost baseline silently.
    """
    profile = _profile("anthropic_messages")
    first = _anthropic_evidence_first_payload(
        document_context=_empty_context(),
        fields=[],
        model="claude-test",
        profile=profile,
    )
    second = _anthropic_evidence_first_payload(
        document_context=_empty_context(),
        fields=[],
        model="claude-test",
        profile=profile,
    )
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_gemini_evidence_first_payload_uses_native_response_schema():
    """The Gemini payload uses systemInstruction + responseSchema for
    structured JSON output, which is more reliable than asking for JSON
    in the prompt and parsing free text."""
    profile = _profile("google_gemini")
    payload = _gemini_evidence_first_payload(
        document_context=_empty_context(),
        fields=[],
        model="gemini-test",
        profile=profile,
    )
    # systemInstruction carries the prompt prefix; responseMimeType +
    # responseSchema lock the output shape.
    assert "systemInstruction" in payload
    assert payload["systemInstruction"]["parts"][0]["text"].startswith(
        # The prompt prefix begins with the document profile's extraction
        # system prompt; we assert it contains our cacheable boilerplate.
        ""
    )
    assert "证据绑定要求" in payload["systemInstruction"]["parts"][0]["text"]
    assert payload["generationConfig"]["responseMimeType"] == "application/json"
    schema = payload["generationConfig"]["responseSchema"]
    # The schema must point to the evidence_candidates root.
    assert "properties" in schema
    assert "evidence_candidates" in schema["properties"]


def test_gemini_response_schema_translates_json_schema_to_openapi_dialect():
    """Gemini responseSchema rejects JSON Schema features it does not
    accept (`additionalProperties`, type-arrays). The translator must
    drop them and fold `type: ['string', 'null']` into `nullable: true`."""
    raw = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "name": {"type": "string"},
            "age": {"type": ["integer", "null"]},
        },
    }
    translated = _gemini_response_schema(raw)
    assert "additionalProperties" not in translated
    assert translated["type"] == "OBJECT"
    assert translated["properties"]["age"]["type"] == "INTEGER"
    assert translated["properties"]["age"]["nullable"] is True
    assert translated["properties"]["name"]["type"] == "STRING"


# ---------------------------------------------------------------------------
# Adapter contract: collect_evidence is no longer a delegation shim
# ---------------------------------------------------------------------------


def test_anthropic_collect_evidence_is_real_implementation():
    """`AnthropicMessagesProvider.collect_evidence` must call its remote
    payload helper. The pre-Phase-3 shim returned `local_evidence_fallback_usage()`
    immediately; the new implementation must reference the Anthropic
    payload builder so a refactor that drops the call fails this test.
    """
    source = inspect.getsource(AnthropicMessagesProvider.collect_evidence)
    assert "_anthropic_evidence_first_payload" in source
    assert "client.post" in source
    assert "v1/messages" in source


def test_gemini_collect_evidence_is_real_implementation():
    """`GoogleGeminiProvider.collect_evidence` must call its remote
    payload helper, not return a local shim."""
    source = inspect.getsource(GoogleGeminiProvider.collect_evidence)
    assert "_gemini_evidence_first_payload" in source
    assert "client.post" in source
    assert "generateContent" in source


def test_openai_compatible_collect_evidence_is_real_implementation():
    """Sanity check that Phase 2's OpenAI-compatible collect_evidence
    has not regressed back to a local shim."""
    source = inspect.getsource(OpenAICompatibleChatProvider.collect_evidence)
    assert "_chat_completions_evidence_first_payload" in source
    # The collect_evidence body delegates the actual upstream invocation
    # to `_run_chat_request` (introduced by M1-001 to share the
    # api_key + base_url retry matrix between extract_group and
    # collect_evidence). The upstream call lives there; assert the
    # helper itself still calls the OpenAI client.
    assert "_run_chat_request" in source
    helper_source = inspect.getsource(OpenAICompatibleChatProvider._run_chat_request)
    assert "client.chat.completions.create" in helper_source


# ---------------------------------------------------------------------------
# Registry contract
# ---------------------------------------------------------------------------


def test_registry_covers_every_catalog_provider():
    """The registry's known kinds must be a superset of the catalog.

    Adding a new provider literal to `config/model_providers/mainstream.yaml`
    without registering an adapter for it must fail this test.
    """
    catalog_path = (
        Path(__file__).resolve().parents[2]
        / "config"
        / "model_providers"
        / "mainstream.yaml"
    )
    payload = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    declared: set[str] = set()
    api_aliases_to_python_kind = {
        "openai-responses": "openai_responses",
        "openai-completions": "openai_compatible",
        "openai-chat": "openai_compatible",
        "anthropic-messages": "anthropic_messages",
        "google-gemini": "google_gemini",
        "disabled": "disabled",
    }
    for entry in payload.get("providers", []) or []:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("provider_kind") or entry.get("provider") or entry.get("api")
        if isinstance(kind, str) and kind:
            declared.add(api_aliases_to_python_kind.get(kind, kind))
    declared.discard("disabled")  # disabled is a sentinel, not a registry entry
    assert declared <= registered_provider_kinds(), (
        f"catalog declares provider kinds {declared - registered_provider_kinds()} "
        "without a registry entry. Add them to "
        "services/llm_provider/registry.py:_PROVIDER_REGISTRY."
    )


def test_registry_dispatches_each_known_kind(monkeypatch):
    """Every registered provider kind constructs the matching adapter.

    Stubs `api_keys_for_profile` so no real credentials are required.
    """
    monkeypatch.setattr(
        "app.services.llm_provider.adapters.api_keys_for_profile",
        lambda profile: ["test-key"],
    )
    expected = {
        "openai_responses": "OpenAIResponsesProvider",
        "openai_compatible": "OpenAICompatibleChatProvider",
        "anthropic_messages": "AnthropicMessagesProvider",
        "google_gemini": "GoogleGeminiProvider",
    }
    for kind, adapter_name in expected.items():
        adapter = provider_for_profile(_profile(kind))
        assert type(adapter).__name__ == adapter_name


def test_registry_rejects_unknown_provider_kind():
    """An unknown provider kind raises a clear runtime error that names
    the offending profile."""
    profile = _profile("not_a_real_provider")
    with pytest.raises(RuntimeError) as exc:
        provider_for_profile(profile)
    message = str(exc.value)
    assert "Unknown provider kind" in message
    assert "not_a_real_provider" in message


def test_registry_rejects_remote_kind_in_local_mode(monkeypatch):
    """An adapter that requires `auto` / `online` must not be reachable
    when llm_mode is set to `local`.

    Preserves the pre-registry rule that only `openai_compatible` (which
    can talk to local Ollama / LM Studio servers) participates in
    `local` mode.
    """
    monkeypatch.setattr(
        "app.services.llm_provider.registry.settings.llm_mode", "local"
    )
    profile = _profile("anthropic_messages")
    with pytest.raises(RuntimeError) as exc:
        provider_for_profile(profile)
    assert "not runnable in current mode" in str(exc.value)


def test_registry_allows_openai_compatible_in_local_mode(monkeypatch):
    """`openai_compatible` adapters can run in `local` mode because they
    accept a base_url override pointing at a local model server."""
    monkeypatch.setattr(
        "app.services.llm_provider.registry.settings.llm_mode", "local"
    )
    monkeypatch.setattr(
        "app.services.llm_provider.adapters.api_keys_for_profile",
        lambda profile: ["test-key"],
    )
    adapter = provider_for_profile(_profile("openai_compatible"))
    assert type(adapter).__name__ == "OpenAICompatibleChatProvider"


# ---------------------------------------------------------------------------
# Privacy boundary still holds
# ---------------------------------------------------------------------------


def test_anthropic_collect_evidence_falls_back_under_safe_evidence_only(monkeypatch):
    """The medical schema's `safe_evidence_only` policy must still block
    full DocumentContext upload to Anthropic. No exposure-policy override
    means the adapter never reaches the network and surfaces the reason."""
    set_runtime_exposure_policy_override(None)
    monkeypatch.setattr(
        "app.services.llm_provider.adapters.api_keys_for_profile",
        lambda profile: ["test-key"],
    )
    monkeypatch.setattr(
        "app.services.llm_provider.payloads.load_extraction_schema",
        lambda: SimpleNamespace(
            remote_exposure_policy=RemoteExposurePolicy(
                allow_full_document_context=False,
                allow_raw_block_text=False,
                allow_safe_evidence_candidates=True,
                allow_page_images=False,
            )
        ),
    )
    # Disable the disk cache so a stale entry from a prior run cannot
    # mask the policy-block branch we are testing.
    monkeypatch.setattr(
        "app.services.llm_provider.adapters._read_evidence_candidate_cache",
        lambda key: None,
    )
    monkeypatch.setattr(
        "app.services.llm_provider.adapters._write_evidence_candidate_cache",
        lambda key, value: None,
    )
    profile = _profile("anthropic_messages")
    adapter = AnthropicMessagesProvider(profile)
    ctx = _empty_context()
    result = adapter.collect_evidence(document_context=ctx, fields=[])
    assert result == local_collect_evidence_fallback(ctx, [])
    assert adapter.last_usage.get("remote_skipped_reason") == "remote_full_context_disabled"
    assert adapter.last_usage.get("evidence_collection_method") == "local_fallback"


def test_gemini_collect_evidence_falls_back_under_safe_evidence_only(monkeypatch):
    """Symmetric to the Anthropic case. The medical schema's safe-evidence
    default must still block Gemini from receiving full DocumentContext."""
    set_runtime_exposure_policy_override(None)
    monkeypatch.setattr(
        "app.services.llm_provider.adapters.api_keys_for_profile",
        lambda profile: ["test-key"],
    )
    monkeypatch.setattr(
        "app.services.llm_provider.payloads.load_extraction_schema",
        lambda: SimpleNamespace(
            remote_exposure_policy=RemoteExposurePolicy(
                allow_full_document_context=False,
                allow_raw_block_text=False,
                allow_safe_evidence_candidates=True,
                allow_page_images=False,
            )
        ),
    )
    monkeypatch.setattr(
        "app.services.llm_provider.adapters._read_evidence_candidate_cache",
        lambda key: None,
    )
    monkeypatch.setattr(
        "app.services.llm_provider.adapters._write_evidence_candidate_cache",
        lambda key, value: None,
    )
    profile = _profile("google_gemini")
    adapter = GoogleGeminiProvider(profile)
    ctx = _empty_context()
    result = adapter.collect_evidence(document_context=ctx, fields=[])
    assert result == local_collect_evidence_fallback(ctx, [])
    assert adapter.last_usage.get("remote_skipped_reason") == "remote_full_context_disabled"
    assert adapter.last_usage.get("evidence_collection_method") == "local_fallback"
