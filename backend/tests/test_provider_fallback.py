from types import SimpleNamespace

from app.domain.models import DocumentIR, FieldGroup
from app.services import provider as provider_module
from app.services.provider import (
    ModelFallbackProvider,
    OpenAICompatibleChatProvider,
    SemanticExtractionProvider,
    _api_keys_for_attempts,
    _candidates_from_text,
    _openai_compatible_base_url_candidates,
    _mark_api_key_cooldown,
)


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
    monkeypatch.setattr(provider_module, "_provider_for_profile", lambda profile: _AlwaysFailingProvider())
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


def test_rate_limited_api_key_is_skipped_during_cooldown(monkeypatch):
    profile = SimpleNamespace(
        model_ref="custom/demo-model",
        provider_id="custom",
        profile_id="provider_custom_demo_model",
        model="demo-model",
    )
    provider_module._API_KEY_COOLDOWN_UNTIL.clear()
    monkeypatch.setattr(provider_module.settings, "model_key_cooldown_seconds", 30, raising=False)

    _mark_api_key_cooldown(profile, "rate-limited-key", RuntimeError("rate limit exceeded"))

    assert _api_keys_for_attempts(profile, ["rate-limited-key", "healthy-key"]) == ["healthy-key"]
    provider_module._API_KEY_COOLDOWN_UNTIL.clear()


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

    monkeypatch.setattr(provider_module, "api_keys_for_profile", lambda profile: ["sk-relay"])
    monkeypatch.setattr(provider_module, "_llm_cache_key", lambda *args, **kwargs: "cache-key")
    monkeypatch.setattr(provider_module, "_read_llm_result_cache", lambda cache_key: None)
    monkeypatch.setattr(provider_module, "_write_llm_result_cache", lambda cache_key, result: None)
    monkeypatch.setattr(
        provider_module,
        "_chat_completions_payload",
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

    monkeypatch.setattr(provider_module, "api_keys_for_profile", lambda profile: ["sk-relay"])
    monkeypatch.setattr(provider_module, "_llm_cache_key", lambda *args, **kwargs: "cache-key")
    monkeypatch.setattr(provider_module, "_read_llm_result_cache", lambda cache_key: None)
    monkeypatch.setattr(provider_module, "_write_llm_result_cache", lambda cache_key, result: None)
    monkeypatch.setattr(
        provider_module,
        "_chat_completions_payload",
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

    monkeypatch.setattr(provider_module, "api_keys_for_profile", lambda profile: ["sk-relay"])
    monkeypatch.setattr(provider_module, "_llm_cache_key", lambda *args, **kwargs: "cache-key")
    monkeypatch.setattr(provider_module, "_read_llm_result_cache", lambda cache_key: None)
    monkeypatch.setattr(provider_module, "_write_llm_result_cache", lambda cache_key, result: None)
    monkeypatch.setattr(
        provider_module,
        "_chat_completions_payload",
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
