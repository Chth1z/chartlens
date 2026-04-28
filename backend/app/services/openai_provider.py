from __future__ import annotations

import json
import time
from typing import Any

import httpx

from app.core.config import settings
from app.schemas.pipeline import EvidenceCandidate, FieldExtractionResult
from app.services.field_dictionary import FieldDefinition
from app.services.model_provider import HeuristicModelProvider, ModelProvider
from app.services.chatgpt_token_store import (
    get_chatgpt_access_token,
    has_chatgpt_model_auth,
    refresh_chatgpt_tokens,
)
from app.services.system_config import load_system_config


class OpenAIResponsesProvider(ModelProvider):
    name = "openai-responses"

    def __init__(self, *, mode: str = "standard") -> None:
        if not settings.openai_api_key:
            raise RuntimeError("EYES_OPENAI_API_KEY is required for OpenAIResponsesProvider")
        from openai import OpenAI

        self.client = OpenAI(api_key=settings.openai_api_key)
        self.mode = mode
        self.model = settings.openai_thorough_model if mode == "thorough" else settings.openai_standard_model
        self.last_usage: dict[str, float | int] = {}

    def extract_fields(
        self,
        *,
        case_id: str,
        fields: list[FieldDefinition],
        evidence_by_field: dict[str, list[EvidenceCandidate]],
    ) -> list[FieldExtractionResult]:
        llm_profile = load_system_config().llm.profiles.get(self.mode) or load_system_config().llm.profiles["standard"]
        request_payload = _build_responses_payload(
            case_id=case_id,
            fields=fields,
            evidence_by_field=evidence_by_field,
            model=self.model,
            prompt_cache_key=llm_profile.prompt_cache_key,
        )
        response = self.client.responses.create(
            **request_payload,
        )
        usage = getattr(response, "usage", None)
        input_details = getattr(usage, "input_tokens_details", None) or getattr(usage, "prompt_tokens_details", None)
        self.last_usage = {
            "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
            "cached_input_tokens": int(getattr(input_details, "cached_tokens", 0) or 0),
            "cost_usd": 0.0,
        }
        text = response.output_text

        parsed = json.loads(text)
        return [FieldExtractionResult.model_validate(item) for item in parsed["results"]]


class ChatGptCodexResponsesProvider(ModelProvider):
    name = "chatgpt-codex-responses"

    def __init__(self, *, mode: str = "standard") -> None:
        self.mode = mode
        self.model = settings.openai_thorough_model if mode == "thorough" else settings.openai_standard_model
        self.last_usage: dict[str, float | int] = {}

    def extract_fields(
        self,
        *,
        case_id: str,
        fields: list[FieldDefinition],
        evidence_by_field: dict[str, list[EvidenceCandidate]],
    ) -> list[FieldExtractionResult]:
        llm_profile = load_system_config().llm.profiles.get(self.mode) or load_system_config().llm.profiles["standard"]
        request_payload = _build_responses_payload(
            case_id=case_id,
            fields=fields,
            evidence_by_field=evidence_by_field,
            model=self.model,
            prompt_cache_key=llm_profile.prompt_cache_key,
        )
        request_payload = _prepare_chatgpt_codex_payload(request_payload)
        payload = self._post_responses(request_payload)
        self.last_usage = _usage_from_response_payload(payload)
        parsed = json.loads(_extract_response_text(payload))
        return [FieldExtractionResult.model_validate(item) for item in parsed["results"]]

    def _post_responses(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._post_once(payload)
        if response.status_code == 401:
            refresh_chatgpt_tokens()
            response = self._post_once(payload)
        if response.is_error:
            detail = response.text.replace("\n", " ").strip()[:500]
            raise RuntimeError(f"ChatGPT/Codex responses failed with HTTP {response.status_code}: {detail}")
        text = response.text
        if "event:" in text and "data:" in text:
            return _parse_sse_response(text)
        return response.json()

    def _post_once(self, payload: dict[str, Any]) -> httpx.Response:
        token = get_chatgpt_access_token()
        last_error: httpx.TransportError | None = None
        for attempt in range(3):
            try:
                return httpx.post(
                    settings.chatgpt_codex_responses_url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "text/event-stream",
                        "Content-Type": "application/json",
                    },
                    timeout=60,
                )
            except httpx.TransportError as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.8 * (attempt + 1))
        raise RuntimeError(f"ChatGPT/Codex transport failed: {last_error}") from last_error


def build_model_provider() -> ModelProvider:
    auth_mode = settings.openai_auth_mode
    if auth_mode != "disabled" and auth_mode in {"auto", "api_key"} and settings.openai_api_key:
        return OpenAIResponsesProvider(mode=settings.model_mode)
    if auth_mode != "disabled" and auth_mode in {"auto", "chatgpt"} and has_chatgpt_model_auth():
        return ChatGptCodexResponsesProvider(mode=settings.model_mode)
    return HeuristicModelProvider()


def _build_responses_payload(
    *,
    case_id: str,
    fields: list[FieldDefinition],
    evidence_by_field: dict[str, list[EvidenceCandidate]],
    model: str,
    prompt_cache_key: str,
) -> dict[str, Any]:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "results": {
                "type": "array",
                "items": _field_result_schema(),
            }
        },
        "required": ["results"],
    }
    user_payload = {
        "case_id": case_id,
        "unresolved_fields": [field.key for field in fields],
        "field_specs": [_field_prompt_spec(field) for field in fields],
        "evidence_by_field": {
            key: [candidate.model_dump() for candidate in candidates]
            for key, candidates in evidence_by_field.items()
            if key != "__case_context__"
        },
        "case_context": [
            candidate.model_dump()
            for candidate in evidence_by_field.get("__case_context__", [])
        ],
        "rules": [
            "Only use the supplied de-identified evidence.",
            "Do not guess. Use unknown and review_required=true when evidence is insufficient.",
            "Return normalized_code only from allowed_codes.",
            "Keep reasoning_summary short and evidence based.",
            "Prefer explicit field evidence; use case_context only to resolve labels, negation, conflicts, and nearby clinical context.",
            "For history fields, distinguish positive history from negated phrases such as 否认/无/未见.",
            "If evidence is contradictory, set review_required=true and error_code='CONFLICT'.",
        ],
    }
    return {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": (
                    "You extract structured clinical research fields from de-identified Chinese medical records. "
                    "You understand noisy OCR, Chinese medical note sections, negation, and field coding rules. "
                    "Never infer a value without evidence."
                ),
            },
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "text": {"format": {"type": "json_schema", "name": "clinical_field_extraction", "strict": True, "schema": schema}},
        "prompt_cache_key": prompt_cache_key,
    }


def _field_prompt_spec(field: FieldDefinition) -> dict[str, Any]:
    return {
        "key": field.key,
        "label": field.label,
        "allowed_codes": field.allowed_codes,
        "target_sections": field.source_sections,
        "decision_rule_summary": _decision_rule_summary(field),
    }


def _decision_rule_summary(field: FieldDefinition) -> str:
    strategy = field.rule_strategy or {}
    kind = str(strategy.get("kind", "keyword"))
    if kind == "history":
        positive = ", ".join((strategy.get("positive_patterns") or [])[:8])
        negative = ", ".join((strategy.get("negative_patterns") or [])[:8])
        return f"history field; positive terms: {positive}; negative terms: {negative}; unknown when evidence is insufficient"
    if kind == "mapping":
        mapping = strategy.get("mapping") or {}
        if isinstance(mapping, dict):
            return "mapping field; choose one allowed code from mapped clinical terms"
    if kind == "regex":
        return "regex/rule-first field; use evidence text and allowed codes only"
    return "keyword/rule-first field; use evidence text and allowed codes only"


def _field_result_schema() -> dict[str, Any]:
    properties: dict[str, Any] = {
        "field_key": {"type": "string"},
        "raw_value": {"type": ["string", "null"]},
        "normalized_code": {"type": ["string", "null"]},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "evidence_text": {"type": ["string", "null"]},
        "page": {"type": ["integer", "null"], "minimum": 1},
        "bbox": {"type": "array", "items": {"type": "number"}},
        "reasoning_summary": {"type": ["string", "null"]},
        "review_required": {"type": "boolean"},
        "error_code": {"type": ["string", "null"]},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties),
    }


def _extract_response_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    texts: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        content = item.get("content") or []
        if isinstance(content, str):
            texts.append(content)
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and part.get("type") in {"output_text", "text"}:
                texts.append(text)
    if texts:
        return "".join(texts)

    choices = payload.get("choices") or []
    for choice in choices:
        message = choice.get("message") if isinstance(choice, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            return content

    raise ValueError("Responses payload did not contain output text")


def _prepare_chatgpt_codex_payload(payload: dict[str, Any]) -> dict[str, Any]:
    prepared = dict(payload)
    input_items = prepared.get("input") or []
    instructions: list[str] = []
    user_items: list[dict[str, Any]] = []
    for item in input_items:
        if not isinstance(item, dict):
            continue
        if item.get("role") == "system":
            content = item.get("content")
            if isinstance(content, str) and content.strip():
                instructions.append(content)
        else:
            user_items.append(item)

    prepared["instructions"] = "\n".join(instructions) or "Extract structured clinical research fields from supplied evidence."
    prepared["input"] = user_items
    prepared["store"] = False
    prepared["stream"] = True
    return prepared


def _parse_sse_response(text: str) -> dict[str, Any]:
    output_parts: list[str] = []
    completed_payload: dict[str, Any] = {}
    for event in text.split("\n\n"):
        data_lines = [line.removeprefix("data: ").strip() for line in event.splitlines() if line.startswith("data:")]
        if not data_lines:
            continue
        data_text = "\n".join(data_lines)
        if data_text == "[DONE]":
            continue
        try:
            payload = json.loads(data_text)
        except json.JSONDecodeError:
            continue
        event_type = payload.get("type")
        if event_type == "response.output_text.delta":
            delta = payload.get("delta")
            if isinstance(delta, str):
                output_parts.append(delta)
        elif event_type == "response.output_text.done" and not output_parts:
            done_text = payload.get("text")
            if isinstance(done_text, str):
                output_parts.append(done_text)
        elif event_type == "response.completed":
            response = payload.get("response")
            if isinstance(response, dict):
                completed_payload = response

    response_payload = dict(completed_payload)
    if output_parts:
        response_payload["output_text"] = "".join(output_parts)
    if "usage" not in response_payload:
        response_payload["usage"] = {}
    return response_payload


def _usage_from_response_payload(payload: dict[str, Any]) -> dict[str, int | float]:
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    input_details = usage.get("input_tokens_details") if isinstance(usage.get("input_tokens_details"), dict) else {}
    return {
        "input_tokens": int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or usage.get("completion_tokens") or 0),
        "cached_input_tokens": int(input_details.get("cached_tokens") or 0),
        "cost_usd": 0.0,
    }
