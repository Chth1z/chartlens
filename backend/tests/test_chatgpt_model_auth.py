import base64
import json
import time

from app.core.config import settings
from app.services.auth import AuthUser, auth_status_from_request
from app.services.chatgpt_token_store import (
    get_chatgpt_access_token,
    has_chatgpt_model_auth,
    load_chatgpt_tokens,
    save_chatgpt_tokens,
)
from app.services.field_dictionary import FieldDefinition
from app.services.openai_provider import (
    ChatGptCodexResponsesProvider,
    _build_responses_payload,
    _extract_response_text,
    _parse_sse_response,
    _prepare_chatgpt_codex_payload,
    build_model_provider,
)


def test_chatgpt_token_cache_enables_model_auth(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "chatgpt_token_cache_path", tmp_path / "chatgpt_tokens.json", raising=False)
    token_payload = {
        "access_token": _jwt({"exp": int(time.time()) + 3600}),
        "refresh_token": "refresh-token",
        "id_token": _jwt({"sub": "user-1", "email": "user@example.com"}),
        "expires_in": 3600,
    }

    save_chatgpt_tokens(token_payload, AuthUser(sub="user-1", email="user@example.com"))

    assert has_chatgpt_model_auth() is True
    assert get_chatgpt_access_token() == token_payload["access_token"]
    cached = load_chatgpt_tokens()
    assert cached is not None
    assert cached["user"]["email"] == "user@example.com"


def test_provider_prefers_chatgpt_codex_token_when_api_key_is_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "chatgpt_token_cache_path", tmp_path / "chatgpt_tokens.json", raising=False)
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "openai_auth_mode", "auto", raising=False)
    save_chatgpt_tokens(
        {
            "access_token": _jwt({"exp": int(time.time()) + 3600}),
            "refresh_token": "refresh-token",
            "id_token": _jwt({"sub": "user-1"}),
        },
        AuthUser(sub="user-1"),
    )

    provider = build_model_provider()

    assert isinstance(provider, ChatGptCodexResponsesProvider)
    assert provider.name == "chatgpt-codex-responses"


def test_auth_status_reports_model_auth_source(tmp_path, monkeypatch):
    class RequestStub:
        cookies: dict[str, str] = {}

    monkeypatch.setattr(settings, "oauth_enabled", False)
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "openai_auth_mode", "auto", raising=False)
    monkeypatch.setattr(settings, "chatgpt_token_cache_path", tmp_path / "chatgpt_tokens.json", raising=False)

    status = auth_status_from_request(RequestStub())
    assert status["model_auth"]["provider"] == "local_fallback"
    assert status["model_auth"]["online_model_available"] is False

    save_chatgpt_tokens(
        {
            "access_token": _jwt({"exp": int(time.time()) + 3600}),
            "refresh_token": "refresh-token",
            "id_token": _jwt({"sub": "user-1"}),
        },
        AuthUser(sub="user-1"),
    )
    status = auth_status_from_request(RequestStub())
    assert status["model_auth"]["provider"] == "chatgpt_codex"
    assert status["model_auth"]["online_model_available"] is True


def test_extract_response_text_handles_raw_responses_payload():
    payload = {
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": '{"results":[]}'},
                ],
            }
        ]
    }

    assert _extract_response_text(payload) == '{"results":[]}'


def test_chatgpt_codex_payload_uses_streaming_requirements():
    payload = {
        "model": "gpt-5.4-mini",
        "input": [
            {"role": "system", "content": "System instructions"},
            {"role": "user", "content": "User payload"},
        ],
        "text": {"format": {"type": "text"}},
        "prompt_cache_key": "cache-key",
    }

    prepared = _prepare_chatgpt_codex_payload(payload)

    assert prepared["instructions"] == "System instructions"
    assert prepared["input"] == [{"role": "user", "content": "User payload"}]
    assert prepared["store"] is False
    assert prepared["stream"] is True


def test_responses_schema_is_strict_for_field_results():
    payload = _build_responses_payload(
        case_id="CASE-SCHEMA",
        fields=[
            FieldDefinition(
                key="gender",
                label="性别",
                export_header="性别",
                allowed_codes=["1", "2", "unknown"],
            )
        ],
        evidence_by_field={},
        model="gpt-5.4-mini",
        prompt_cache_key="cache-key",
    )

    item_schema = payload["text"]["format"]["schema"]["properties"]["results"]["items"]
    assert item_schema["additionalProperties"] is False
    assert set(item_schema["required"]) == set(item_schema["properties"])


def test_parse_sse_response_extracts_text_and_usage():
    sse = "\n\n".join(
        [
            'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"{\\"results\\":["}',
            'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"]}"}',
            'event: response.completed\ndata: {"type":"response.completed","response":{"usage":{"input_tokens":12,"output_tokens":5}}}',
        ]
    )

    payload = _parse_sse_response(sse)

    assert payload["output_text"] == '{"results":[]}'
    assert payload["usage"]["input_tokens"] == 12
    assert payload["usage"]["output_tokens"] == 5


def _jwt(payload: dict) -> str:
    header = {"alg": "none", "typ": "JWT"}
    parts = [
        base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("="),
        base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("="),
        "",
    ]
    return ".".join(parts)
