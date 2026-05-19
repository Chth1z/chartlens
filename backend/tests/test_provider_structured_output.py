"""Contract tests for M1-001 provider-capability-aware structured output.

Pins the rules established by `docs/MODERNIZATION_PLAN.md` M1-001:

1. Every `ModelProfile` YAML in `config/model_profiles/` declares an
   explicit `structured_output_mode` from the allowed set.
2. The OpenAI-compatible chat payload builder emits the right
   `response_format` shape per mode: strict json_schema descriptor for
   `json_schema`, plain `{"type":"json_object"}` for `json_object`.
3. The system prompt drops the embedded schema descriptor when the API
   layer enforces it (json_schema), and keeps it when the API layer is
   only doing a json_object validation (json_object).
4. The OpenAI-compatible adapter catches a 400-class capability error
   on the first request, downgrades the mode to the next-weaker one,
   and retries once. The downgrade is recorded in
   `last_usage["structured_output_mode"]` and
   `last_usage["structured_output_downgrade"]`.
5. The evidence-first cache key changes when the
   `structured_output_mode` changes, so switching modes invalidates the
   cache automatically.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from app.core.config_loader import load_extraction_schema
from app.domain.models import (
    DocumentIR,
    DocumentIRBlock,
    FieldGroup,
    ModelProfile,
)
from app.services.document_context import build_document_context
from app.services.llm_provider.adapters import OpenAICompatibleChatProvider
from app.services.llm_provider.cache import _evidence_first_cache_key
from app.services.llm_provider.payloads import (
    _chat_completions_payload,
    _chat_response_format_for_mode,
)
from app.services.llm_provider.payloads_evidence_first import (
    _chat_completions_evidence_first_payload,
)


ALLOWED_MODES = {"json_schema", "json_object", "tools", "text"}


# ---------------------------------------------------------------------------
# 1) Every model profile YAML declares structured_output_mode in the allowed
#    set, and ModelProfile parses it cleanly.
# ---------------------------------------------------------------------------


def test_every_model_profile_declares_structured_output_mode():
    profiles_dir = Path(__file__).resolve().parents[2] / "config" / "model_profiles"
    yaml_files = sorted(profiles_dir.glob("*.yaml"))
    assert yaml_files, "expected at least one model profile YAML"

    for path in yaml_files:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(payload, dict), f"{path.name} did not parse as a mapping"
        assert "structured_output_mode" in payload, (
            f"{path.name} is missing the M1-001 structured_output_mode field"
        )
        assert payload["structured_output_mode"] in ALLOWED_MODES, (
            f"{path.name} declares structured_output_mode={payload['structured_output_mode']!r}, "
            f"which is not in {sorted(ALLOWED_MODES)}"
        )
        # The Pydantic model must accept the YAML as-is.
        profile = ModelProfile.model_validate(payload)
        assert profile.structured_output_mode == payload["structured_output_mode"]


# ---------------------------------------------------------------------------
# 2) Helper round-trip: every supported mode produces the expected
#    response_format shape; unsupported modes raise.
# ---------------------------------------------------------------------------


def test_chat_response_format_helper_emits_strict_json_schema():
    schema = {"type": "object", "properties": {}, "required": []}
    rf = _chat_response_format_for_mode(
        "json_schema", schema=schema, schema_name="eyex_test"
    )
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "eyex_test"
    assert rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"] is schema


def test_chat_response_format_helper_emits_json_object():
    rf = _chat_response_format_for_mode(
        "json_object", schema={}, schema_name="eyex_test"
    )
    assert rf == {"type": "json_object"}


@pytest.mark.parametrize("mode", ["tools", "text", "garbage"])
def test_chat_response_format_helper_rejects_unsupported_modes(mode):
    with pytest.raises(ValueError):
        _chat_response_format_for_mode(mode, schema={}, schema_name="eyex_test")


# ---------------------------------------------------------------------------
# 3) Payload builder behavior per mode.
# ---------------------------------------------------------------------------


def _build_evidence_first_inputs():
    schema = load_extraction_schema()
    field = schema.field_by_key("gender")
    context = build_document_context(
        DocumentIR(
            document_id="case-structured-output",
            profile_id="medical_inpatient_zh",
            source_filename="case.pdf",
            blocks=[
                DocumentIRBlock(
                    block_id="b1",
                    page=1,
                    reading_order=1,
                    text="性别：男",
                    confidence=0.98,
                    section_label="基本信息",
                )
            ],
        )
    )
    return context, field


def _make_profile(structured_output_mode: str) -> SimpleNamespace:
    return SimpleNamespace(
        profile_id="test_profile",
        provider="openai_compatible",
        provider_id="test",
        model="test-model",
        input=["text"],
        max_output_tokens=1024,
        prompt_cache_key="test-cache",
        reasoning_effort="low",
        temperature=0.0,
        structured_output_mode=structured_output_mode,
    )


def test_json_schema_payload_emits_response_format_with_strict_true():
    context, field = _build_evidence_first_inputs()
    profile = _make_profile("json_schema")

    payload = _chat_completions_evidence_first_payload(
        document_context=context,
        fields=[field],
        model="test-model",
        profile=profile,
    )

    response_format = payload["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "eyex_evidence_collection"
    assert response_format["json_schema"]["strict"] is True
    schema = response_format["json_schema"]["schema"]
    assert schema["required"] == ["evidence_candidates"]

    # The system prompt must drop the embedded schema descriptor when the
    # API enforces the schema. We assert the descriptor sentinel does NOT
    # appear.
    system_content = payload["messages"][0]["content"]
    assert "Output one JSON object that strictly matches this schema" not in system_content
    # The base business-rule prose is still present.
    assert "evidence_text 必须为引用 block 的连续子串" in system_content


def test_json_object_payload_keeps_schema_descriptor_in_system_prompt():
    context, field = _build_evidence_first_inputs()
    profile = _make_profile("json_object")

    payload = _chat_completions_evidence_first_payload(
        document_context=context,
        fields=[field],
        model="test-model",
        profile=profile,
    )

    assert payload["response_format"] == {"type": "json_object"}
    system_content = payload["messages"][0]["content"]
    assert "Output one JSON object that strictly matches this schema" in system_content


def test_extract_group_payload_emits_strict_json_schema_when_profile_declares_it():
    profile = _make_profile("json_schema")
    document_ir = DocumentIR(
        document_id="case-1",
        profile_id="medical_inpatient_zh",
        source_filename="case.pdf",
    )
    payload = _chat_completions_payload(
        document_ir=document_ir,
        group=FieldGroup(key="history", label="病史"),
        fields=[],
        blocks=[],
        model="test-model",
        profile=profile,
    )
    rf = payload["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["name"] == "eyex_group_extraction"


# ---------------------------------------------------------------------------
# 4) Adapter capability fallback runs end-to-end against a stub client.
# ---------------------------------------------------------------------------


class _CapabilityError(RuntimeError):
    """Mimics the upstream 400-class shape: status_code attribute plus
    the magic strings the matcher looks for."""

    status_code = 400

    def __init__(self) -> None:
        super().__init__(
            "400 Bad Request: response_format json_schema not supported "
            "(invalid_request_error)"
        )


def test_capability_downgrade_falls_back_to_json_object(monkeypatch, tmp_path):
    """When the upstream rejects json_schema with a 400 capability
    error on the first call, the adapter must rebuild the payload with
    json_object and retry exactly once. last_usage must reflect the
    downgrade.
    """
    context, field = _build_evidence_first_inputs()
    profile = _make_profile("json_schema")

    # Capture the response_format the adapter sends on each attempt.
    sent_response_formats: list[dict] = []

    class _Completions:
        def __init__(self) -> None:
            self.calls = 0

        def create(self, **payload):
            self.calls += 1
            sent_response_formats.append(payload["response_format"])
            if self.calls == 1:
                raise _CapabilityError()
            # Second call returns a valid evidence-candidate payload.
            content = (
                '{"evidence_candidates": [{'
                '"field_key": "gender", '
                '"candidate_value": "男", '
                '"normalized_code": "1", '
                '"evidence_text": "性别：男", '
                '"field_label_seen": "性别", '
                '"source_type": "ocr_text", '
                '"document_region": null, '
                '"visual_confirmed": false, '
                '"block_id": "b1", '
                '"block_ids": ["b1"], '
                '"text": "性别：男", '
                '"page": 1, '
                '"bbox": [], '
                '"confidence": 0.95, '
                '"ocr_confidence": 0.98, '
                '"section_label": "基本信息", '
                '"document_kind": "admission_note", '
                '"forbidden_inference_flags": [], '
                '"conflicts": []}]}'
            )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                usage=SimpleNamespace(prompt_tokens=120, completion_tokens=18),
            )

    completions = _Completions()

    class _FakeClient:
        def __init__(self, *, api_key: str, base_url: str, timeout: float) -> None:
            self.chat = SimpleNamespace(completions=completions)

    # Build the adapter without going through __init__ (which needs a
    # real OpenAI import and credentials lookup).
    adapter = OpenAICompatibleChatProvider.__new__(OpenAICompatibleChatProvider)
    adapter.profile = SimpleNamespace(
        profile_id="test_provider",
        provider="openai_compatible",
        provider_id="test",
        model="test-model",
        api_key_env="EYEX_TEST_API_KEY",
        api_key_value=None,
        base_url="https://stub.example/v1",
        max_output_tokens=1024,
        prompt_cache_key="test-cache",
        reasoning_effort="low",
        temperature=0.0,
        structured_output_mode="json_schema",
        input=["text"],
    )
    adapter.api_keys = ["sk-test"]
    adapter.client_class = _FakeClient
    adapter.base_urls = ["https://stub.example/v1"]
    adapter.base_url = adapter.base_urls[0]
    adapter.model = "test-model"
    adapter.name = "test_provider-chat"

    # Force cache miss + isolate cache writes.
    monkeypatch.setattr(
        "app.services.llm_provider.adapters._read_evidence_candidate_cache",
        lambda key: None,
    )
    written: dict[str, object] = {}
    monkeypatch.setattr(
        "app.services.llm_provider.adapters._write_evidence_candidate_cache",
        lambda key, result: written.setdefault(key, result),
    )

    # Allow full document context to the (stubbed) remote so the adapter
    # actually runs the API call path; otherwise it short-circuits to
    # local rule extraction and never exercises the downgrade ladder.
    from app.domain.models import RemoteExposurePolicy
    from app.services.llm_provider import payloads as _payloads_module

    permissive = RemoteExposurePolicy(
        allow_full_document_context=True,
        allow_raw_block_text=True,
        allow_safe_evidence_candidates=True,
    )
    _payloads_module.set_runtime_exposure_policy_override(permissive)
    try:
        result = adapter.collect_evidence(document_context=context, fields=[field])
    finally:
        _payloads_module.set_runtime_exposure_policy_override(None)

    assert completions.calls == 2
    # First attempt = json_schema, second attempt = json_object.
    assert sent_response_formats[0]["type"] == "json_schema"
    assert sent_response_formats[1] == {"type": "json_object"}

    # The result is the second call's payload, properly parsed.
    assert "gender" in result
    assert result["gender"][0].normalized_code == "1"

    assert adapter.last_usage["structured_output_mode"] == "json_object"
    downgrade = adapter.last_usage.get("structured_output_downgrade")
    assert isinstance(downgrade, str) and downgrade
    assert "json_schema" in downgrade and "json_object" in downgrade


# ---------------------------------------------------------------------------
# 5) Cache key flips when structured_output_mode flips.
# ---------------------------------------------------------------------------


def test_cache_key_changes_when_structured_output_mode_changes():
    context, field = _build_evidence_first_inputs()
    profile_strict = _make_profile("json_schema")
    profile_loose = _make_profile("json_object")

    key_strict = _evidence_first_cache_key(
        profile_strict, context, [field], stage="collect"
    )
    key_loose = _evidence_first_cache_key(
        profile_loose, context, [field], stage="collect"
    )

    assert key_strict != key_loose, (
        "Switching structured_output_mode must invalidate the evidence-first "
        "cache, otherwise a downgraded run can read back a cache entry "
        "produced under the stricter mode."
    )
