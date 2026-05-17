from types import SimpleNamespace

import pytest

from app.domain.models import DocumentIR, FieldGroup
from app.domain.models import DocumentIRBlock
from app.core.config_loader import load_extraction_schema
from app.services.document_context import build_document_context
from app.services.llm_provider.fallback import ModelFallbackProvider
from app.services.llm_provider.adapters import OpenAICompatibleChatProvider, OpenAIResponsesProvider
from app.services.llm_provider.types import SemanticExtractionProvider
from app.services.llm_provider.utils import (
    _API_KEY_COOLDOWN_UNTIL,
    _api_keys_for_attempts,
    _mark_api_key_cooldown,
    _openai_compatible_base_url_candidates,
)
from app.services.llm_provider.parsing import (
    _candidates_from_text,
    _evidence_candidates_from_text,
    _evidence_candidate_response_schema,
    _response_schema,
)
from app.services.llm_provider.payloads import _responses_evidence_first_payload
class _AlwaysFailingProvider(SemanticExtractionProvider):
    name = "always-failing"
    route = "online_llm"

    def extract_group(self, *, document_ir, group, fields, blocks):
        raise RuntimeError("upstream model rejected request")


def test_model_fallback_records_failure_reason(monkeypatch):
    profile = SimpleNamespace(
        model_ref="deepseek/deepseek-v4-flash",
        provider_id="deepseek",
        profile_id="deepseek_v4_flash",
        model="deepseek-v4-flash",
    )
    monkeypatch.setattr("app.services.llm_provider.fallback._provider_for_profile", lambda profile: _AlwaysFailingProvider())
    fallback = ModelFallbackProvider([profile])

    fallback.extract_group(
        document_ir=DocumentIR(document_id="case-1", profile_id="default", source_filename="case.pdf"),
        group=FieldGroup(key="history", label="病史"),
        fields=[],
        blocks=[],
    )

    assert fallback.route == "local_after_model_fallback"
    assert fallback.last_usage["fallback_failures"] == 1
    assert fallback.last_usage["fallback_errors"] == [
        "deepseek/deepseek-v4-flash: RuntimeError: upstream model rejected request"
    ]


def test_llm_candidate_parser_accepts_null_bbox_as_empty_list():
    text = """
    {
      "results": [
        {
          "field_key": "age",
          "field_group_key": "demographics",
          "raw_value": "30岁",
          "normalized_code": "30",
          "status": "confirmed",
          "confidence": 0.9,
          "evidence_text": "年龄：30岁",
          "evidence_span": "年龄：30岁",
          "evidence_block_id": "b1",
          "evidence_type": "explicit_positive",
          "page": 1,
          "bbox": null,
          "facts": [],
          "reasoning_summary": "原文明确记录年龄",
          "review_required": false,
          "error_code": null,
          "validator_messages": []
        }
      ]
    }
    """

    candidates = _candidates_from_text(text)

    assert candidates[0].bbox == []


def test_llm_candidate_parser_maps_no_evidence_status_to_not_mentioned():
    text = """
    {
      "results": [
        {
          "field_key": "hypertension_history",
          "field_group_key": "history",
          "raw_value": null,
          "normalized_code": "unknown",
          "status": "no_evidence",
          "confidence": 0,
          "evidence_text": null,
          "evidence_span": null,
          "evidence_block_id": null,
          "evidence_type": "no_evidence",
          "page": null,
          "bbox": [],
          "facts": [],
          "reasoning_summary": "未找到证据",
          "review_required": true,
          "error_code": null,
          "validator_messages": []
        }
      ]
    }
    """

    candidates = _candidates_from_text(text)

    assert candidates[0].status == "not_mentioned"


def test_llm_candidate_parser_accepts_markdown_fenced_json():
    text = """下面是结果：
    ```json
    {"results": []}
    ```
    """

    assert _candidates_from_text(text) == []


def test_llm_candidate_parser_accepts_json_embedded_in_text():
    text = 'Result: {"results": []} done.'

    assert _candidates_from_text(text) == []


def test_llm_candidate_parser_accepts_double_encoded_json_string():
    text = '"{\\"results\\": []}"'

    assert _candidates_from_text(text) == []


def test_evidence_candidate_parser_groups_candidates_by_field():
    text = """
    {
      "evidence_candidates": [
        {
          "field_key": "gender",
          "candidate_value": "男",
          "normalized_code": "1",
          "evidence_text": "性别：男",
          "field_label_seen": "性别",
          "source_type": "ocr_text",
          "document_region": "基本信息",
          "visual_confirmed": false,
          "block_id": "b1",
          "block_ids": ["b1"],
          "text": "性别：男",
          "page": 1,
          "bbox": [],
          "confidence": 0.96,
          "ocr_confidence": 0.98,
          "section_label": "基本信息",
          "document_kind": "admission_note",
          "forbidden_inference_flags": [],
          "conflicts": []
        }
      ]
    }
    """

    grouped = _evidence_candidates_from_text(text)

    assert grouped["gender"][0].normalized_code == "1"
    assert grouped["gender"][0].evidence_text == "性别：男"


def test_responses_evidence_first_payload_carries_remote_safety_policy():
    schema = load_extraction_schema()
    field = schema.field_by_key("gender")
    context = build_document_context(
        DocumentIR(
            document_id="case-context",
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
    profile = SimpleNamespace(
        input=["text"],
        max_output_tokens=1024,
        prompt_cache_key="test-cache",
        reasoning_effort="low",
    )

    payload = _responses_evidence_first_payload(
        document_context=context,
        fields=[field],
        model="gpt-test",
        profile=profile,
    )

    user_content = payload["input"][1]["content"][0]["text"]
    assert '"task": "collect_field_evidence_candidates"' in user_content
    assert '"remote_context_mode": "safe_evidence_only"' in user_content
    assert '"evidence_policy"' in user_content
    assert payload["text"]["format"]["schema"]["required"] == ["evidence_candidates"]


def test_structured_output_schemas_are_strict_mode_compatible():
    for schema in (_response_schema(), _evidence_candidate_response_schema()):
        _assert_strict_json_schema(schema)


def test_responses_evidence_first_payload_minimizes_remote_context_by_default():
    schema = load_extraction_schema()
    field = schema.field_by_key("gender")
    context = build_document_context(
        DocumentIR(
            document_id="case-remote-minimized",
            profile_id="medical_inpatient_zh",
            source_filename="case.pdf",
            blocks=[
                DocumentIRBlock(
                    block_id="b1",
                    page=1,
                    reading_order=1,
                    text="姓名：张三 性别：男 住址：深圳市南山区科技园",
                    confidence=0.98,
                    section_label="基本信息",
                )
            ],
            metadata={
                "page_images": [
                    {
                        "page": 1,
                        "path": "D:/sensitive/original-page.png",
                        "width": 1200,
                        "height": 1600,
                        "online_allowed": True,
                    }
                ]
            },
        )
    )
    profile = SimpleNamespace(
        input=["text", "image"],
        max_output_tokens=1024,
        prompt_cache_key="test-cache",
        reasoning_effort="low",
    )

    payload = _responses_evidence_first_payload(
        document_context=context,
        fields=[field],
        model="gpt-test",
        profile=profile,
    )

    user_content = payload["input"][1]["content"][0]["text"]
    assert '"remote_context_mode": "safe_evidence_only"' in user_content
    assert "张三" not in user_content
    assert "深圳市" not in user_content
    assert "性别：男" not in user_content
    assert "D:/sensitive/original-page.png" not in user_content
    assert all(item["type"] != "input_image" for item in payload["input"][1]["content"])


def _assert_strict_json_schema(schema):
    if schema.get("type") == "object":
        assert schema.get("additionalProperties") is False
        properties = schema.get("properties", {})
        assert sorted(schema.get("required", [])) == sorted(properties)
        for child in properties.values():
            _assert_strict_json_schema(child)
    if schema.get("type") == "array":
        _assert_strict_json_schema(schema.get("items", {}))


def test_online_evidence_collection_uses_local_when_full_context_upload_disabled(monkeypatch):
    schema = load_extraction_schema()
    field = schema.field_by_key("gender")
    context = build_document_context(
        DocumentIR(
            document_id="case-local-evidence-only",
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
    provider = OpenAIResponsesProvider.__new__(OpenAIResponsesProvider)
    provider.profile = SimpleNamespace(
        input=["text", "image"],
        max_output_tokens=1024,
        prompt_cache_key="test-cache",
        reasoning_effort="low",
    )
    provider.api_keys = ["sk-test"]
    provider.model = "gpt-test"
    provider.base_url = None
    provider.client_class = object
    monkeypatch.setattr("app.services.llm_provider.adapters._read_evidence_candidate_cache", lambda cache_key: None)
    monkeypatch.setattr("app.services.llm_provider.adapters._write_evidence_candidate_cache", lambda cache_key, result: None)
    monkeypatch.setattr(
        "app.services.llm_provider.adapters._responses_evidence_first_payload",
        lambda **kwargs: pytest.fail("remote full-context payload should not be built"),
    )

    evidence = provider.collect_evidence(document_context=context, fields=[field])

    assert evidence["gender"][0].normalized_code == "1"
    assert provider.last_usage["remote_skipped_reason"] == "remote_full_context_disabled"


def test_rate_limited_api_key_is_skipped_during_cooldown(monkeypatch):
    profile = SimpleNamespace(
        model_ref="custom/demo-model",
        provider_id="custom",
        profile_id="provider_custom_demo_model",
        model="demo-model",
    )
    _API_KEY_COOLDOWN_UNTIL.clear()
    monkeypatch.setattr("app.services.llm_provider.utils.settings.model_key_cooldown_seconds", 30, raising=False)

    _mark_api_key_cooldown(profile, "rate-limited-key", RuntimeError("rate limit exceeded"))

    assert _api_keys_for_attempts(profile, ["rate-limited-key", "healthy-key"]) == ["healthy-key"]
    _API_KEY_COOLDOWN_UNTIL.clear()


def test_openai_compatible_base_url_candidates_try_v1_for_root_relay():
    assert _openai_compatible_base_url_candidates("https://relay.example.com") == [
        "https://relay.example.com",
        "https://relay.example.com/v1",
    ]
    assert _openai_compatible_base_url_candidates("https://relay.example.com/v1") == [
        "https://relay.example.com/v1"
    ]


def test_openai_compatible_provider_retries_v1_when_root_path_404(monkeypatch):
    profile = SimpleNamespace(
        api_key_env="RELAY_API_KEY",
        base_url="https://relay.example.com",
        fallback_chain=[],
        max_output_tokens=1024,
        model="demo-model",
        model_ref="custom/demo-model",
        profile_id="provider_custom_demo_model",
        prompt_cache_key=None,
        provider="openai_compatible",
        provider_id="custom",
        response_format="json_object",
        temperature=0,
    )
    calls: list[str] = []

    class NotFoundError(RuntimeError):
        status_code = 404

    class FakeCompletions:
        def __init__(self, base_url: str) -> None:
            self.base_url = base_url

        def create(self, **payload):
            calls.append(self.base_url)
            if self.base_url == "https://relay.example.com":
                raise NotFoundError("not found")
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"results": []}'))],
                usage=SimpleNamespace(prompt_tokens=12, completion_tokens=3),
            )

    class FakeClient:
        def __init__(self, *, api_key: str, base_url: str, timeout: float) -> None:
            self.chat = SimpleNamespace(completions=FakeCompletions(base_url))

    monkeypatch.setattr("app.services.llm_provider.adapters.api_keys_for_profile", lambda profile: ["sk-relay"])
    monkeypatch.setattr("app.services.llm_provider.adapters._llm_cache_key", lambda *args, **kwargs: "cache-key")
    monkeypatch.setattr("app.services.llm_provider.adapters._read_llm_result_cache", lambda cache_key: None)
    monkeypatch.setattr("app.services.llm_provider.adapters._write_llm_result_cache", lambda cache_key, result: None)
    monkeypatch.setattr(
        "app.services.llm_provider.adapters._chat_completions_payload",
        lambda **kwargs: {"model": "demo-model", "messages": []},
    )

    provider = OpenAICompatibleChatProvider(profile)
    provider.client_class = FakeClient

    result = provider.extract_group(
        document_ir=DocumentIR(document_id="case-1", profile_id="default", source_filename="case.pdf"),
        group=FieldGroup(key="history", label="病史"),
        fields=[],
        blocks=[],
    )

    assert result == []
    assert calls == ["https://relay.example.com", "https://relay.example.com/v1"]
    assert provider.base_url == "https://relay.example.com/v1"


def test_openai_compatible_provider_retries_v1_when_root_returns_html(monkeypatch):
    profile = SimpleNamespace(
        api_key_env="RELAY_API_KEY",
        base_url="https://relay.example.com",
        fallback_chain=[],
        max_output_tokens=1024,
        model="demo-model",
        model_ref="custom/demo-model",
        profile_id="provider_custom_demo_model",
        prompt_cache_key=None,
        provider="openai_compatible",
        provider_id="custom",
        response_format="json_object",
        temperature=0,
    )
    calls: list[str] = []

    class FakeCompletions:
        def __init__(self, base_url: str) -> None:
            self.base_url = base_url

        def create(self, **payload):
            calls.append(self.base_url)
            if self.base_url == "https://relay.example.com":
                return "<!doctype html><html></html>"
            return '{"results": []}'

    class FakeClient:
        def __init__(self, *, api_key: str, base_url: str, timeout: float) -> None:
            self.chat = SimpleNamespace(completions=FakeCompletions(base_url))

    monkeypatch.setattr("app.services.llm_provider.adapters.api_keys_for_profile", lambda profile: ["sk-relay"])
    monkeypatch.setattr("app.services.llm_provider.adapters._llm_cache_key", lambda *args, **kwargs: "cache-key")
    monkeypatch.setattr("app.services.llm_provider.adapters._read_llm_result_cache", lambda cache_key: None)
    monkeypatch.setattr("app.services.llm_provider.adapters._write_llm_result_cache", lambda cache_key, result: None)
    monkeypatch.setattr(
        "app.services.llm_provider.adapters._chat_completions_payload",
        lambda **kwargs: {"model": "demo-model", "messages": []},
    )

    provider = OpenAICompatibleChatProvider(profile)
    provider.client_class = FakeClient

    result = provider.extract_group(
        document_ir=DocumentIR(document_id="case-1", profile_id="default", source_filename="case.pdf"),
        group=FieldGroup(key="history", label="病史"),
        fields=[],
        blocks=[],
    )

    assert result == []
    assert calls == ["https://relay.example.com", "https://relay.example.com/v1"]
    assert provider.base_url == "https://relay.example.com/v1"


def test_openai_compatible_provider_accepts_plain_string_response(monkeypatch):
    profile = SimpleNamespace(
        api_key_env="RELAY_API_KEY",
        base_url="https://relay.example.com/v1",
        fallback_chain=[],
        max_output_tokens=1024,
        model="demo-model",
        model_ref="custom/demo-model",
        profile_id="provider_custom_demo_model",
        prompt_cache_key=None,
        provider="openai_compatible",
        provider_id="custom",
        response_format="json_object",
        temperature=0,
    )

    class FakeCompletions:
        def create(self, **payload):
            return '{"results": []}'

    class FakeClient:
        def __init__(self, *, api_key: str, base_url: str, timeout: float) -> None:
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("app.services.llm_provider.adapters.api_keys_for_profile", lambda profile: ["sk-relay"])
    monkeypatch.setattr("app.services.llm_provider.adapters._llm_cache_key", lambda *args, **kwargs: "cache-key")
    monkeypatch.setattr("app.services.llm_provider.adapters._read_llm_result_cache", lambda cache_key: None)
    monkeypatch.setattr("app.services.llm_provider.adapters._write_llm_result_cache", lambda cache_key, result: None)
    monkeypatch.setattr(
        "app.services.llm_provider.adapters._chat_completions_payload",
        lambda **kwargs: {"model": "demo-model", "messages": []},
    )

    provider = OpenAICompatibleChatProvider(profile)
    provider.client_class = FakeClient

    result = provider.extract_group(
        document_ir=DocumentIR(document_id="case-1", profile_id="default", source_filename="case.pdf"),
        group=FieldGroup(key="history", label="病史"),
        fields=[],
        blocks=[],
    )

    assert result == []
    assert provider.last_usage["llm_cache_status"] == "miss"
