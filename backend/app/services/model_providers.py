from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import httpx
import yaml
from pydantic import BaseModel, Field

from app.core.settings import settings
from app.domain.models import ModelProfile
from app.services.model_auth import api_keys_for_profile, explicit_api_keys_for_profile, set_runtime_provider_api_key
from app.services.model_selection import set_active_model_profile_object
from app.services.safe_errors import safe_error_message
from app.services.secret_store import save_provider_api_key


ProviderApi = Literal["openai-responses", "openai-completions", "anthropic-messages", "google-gemini", "disabled"]
ModelSource = Literal["fetched", "custom", "preset"]


class ProviderModel(BaseModel):
    id: str
    name: str | None = None
    context_window: int | None = None
    max_tokens: int | None = None
    input: list[str] = Field(default_factory=lambda: ["text"])
    source: ModelSource | None = None
    runnable: bool | None = None


class ProviderCatalogEntry(BaseModel):
    provider_id: str
    label: str
    description: str
    api: ProviderApi
    api_options: list[ProviderApi] = Field(default_factory=list)
    default_base_url: str | None = None
    auth_env_vars: list[str] = Field(default_factory=list)
    auth_optional: bool = False
    base_url_editable: bool = True
    default_models: list[ProviderModel] = Field(default_factory=list)
    option_schema: dict[str, Any] = Field(default_factory=dict)


class StoredProviderSettings(BaseModel):
    provider_id: str
    enabled: bool = True
    api: ProviderApi | None = None
    api_key: str | None = None
    base_url: str | None = None
    selected_model: str | None = None
    custom_models: list[ProviderModel] = Field(default_factory=list)
    fetched_models: list[ProviderModel] = Field(default_factory=list)
    model_settings: dict[str, Any] = Field(default_factory=dict)
    last_error: str | None = None
    connected_at: str | None = None


class ProviderSettingsUpdate(BaseModel):
    enabled: bool | None = None
    api: ProviderApi | None = None
    api_key: str | None = None
    base_url: str | None = None
    selected_model: str | None = None
    custom_models: list[ProviderModel] | None = None
    model_settings: dict[str, Any] | None = None


def _built_in_provider_catalog() -> list[ProviderCatalogEntry]:
    return [
        ProviderCatalogEntry(
            provider_id="openai",
            label="OpenAI",
            description="OpenAI Responses API with strict JSON Schema outputs.",
            api="openai-responses",
            api_options=["openai-responses", "openai-completions"],
            default_base_url="https://api.openai.com/v1",
            auth_env_vars=["EYEX_OPENAI_API_KEY", "OPENAI_API_KEY"],
            base_url_editable=True,
            default_models=[
                ProviderModel(id="gpt-5.4", name="GPT-5.4", context_window=400000, max_tokens=4096),
                ProviderModel(id="gpt-5.4-mini", name="GPT-5.4 Mini", context_window=400000, max_tokens=4096),
                ProviderModel(id="gpt-5.5", name="GPT-5.5", context_window=400000, max_tokens=4096),
            ],
            option_schema={
                "reasoning_effort": ["minimal", "low", "medium", "high", "xhigh"],
                "max_output_tokens": {"min": 256, "max": 8192, "step": 256},
            },
        ),
        ProviderCatalogEntry(
            provider_id="deepseek",
            label="DeepSeek",
            description="DeepSeek OpenAI-compatible chat completions.",
            api="openai-completions",
            default_base_url="https://api.deepseek.com",
            auth_env_vars=["EYEX_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY"],
            base_url_editable=True,
            default_models=[
                ProviderModel(id="deepseek-v4-flash", name="DeepSeek V4 Flash", context_window=1000000, max_tokens=384000),
                ProviderModel(id="deepseek-v4-pro", name="DeepSeek V4 Pro", context_window=1000000, max_tokens=384000),
            ],
            option_schema={
                "temperature": {"min": 0, "max": 1, "step": 0.1},
                "max_output_tokens": {"min": 256, "max": 8192, "step": 256},
            },
        ),
        ProviderCatalogEntry(
            provider_id="anthropic",
            label="Anthropic",
            description="Claude native Messages API.",
            api="anthropic-messages",
            default_base_url="https://api.anthropic.com",
            auth_env_vars=["EYEX_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"],
            default_models=[
                ProviderModel(id="claude-opus-4-6", name="Claude Opus 4.6", context_window=200000, max_tokens=4096),
                ProviderModel(id="claude-sonnet-4-6", name="Claude Sonnet 4.6", context_window=200000, max_tokens=4096),
                ProviderModel(id="claude-haiku-4-6", name="Claude Haiku 4.6", context_window=200000, max_tokens=4096),
            ],
            option_schema={
                "temperature": {"min": 0, "max": 1, "step": 0.1},
                "max_output_tokens": {"min": 256, "max": 8192, "step": 256},
            },
        ),
        ProviderCatalogEntry(
            provider_id="google",
            label="Google Gemini",
            description="Google Gemini native generateContent API.",
            api="google-gemini",
            default_base_url="https://generativelanguage.googleapis.com",
            auth_env_vars=["EYEX_GEMINI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"],
            default_models=[
                ProviderModel(id="gemini-3.1-pro-preview", name="Gemini 3.1 Pro", context_window=1000000, max_tokens=8192),
                ProviderModel(id="gemini-3-flash-preview", name="Gemini 3 Flash", context_window=1000000, max_tokens=8192),
                ProviderModel(id="gemini-2.5-flash", name="Gemini 2.5 Flash", context_window=1000000, max_tokens=8192),
            ],
            option_schema={
                "temperature": {"min": 0, "max": 1, "step": 0.1},
                "max_output_tokens": {"min": 256, "max": 8192, "step": 256},
            },
        ),
        ProviderCatalogEntry(
            provider_id="openrouter",
            label="OpenRouter",
            description="OpenAI-compatible router with broad model catalog.",
            api="openai-completions",
            default_base_url="https://openrouter.ai/api/v1",
            auth_env_vars=["EYEX_OPENROUTER_API_KEY", "OPENROUTER_API_KEY"],
            default_models=[ProviderModel(id="auto", name="Auto")],
            option_schema={
                "temperature": {"min": 0, "max": 1, "step": 0.1},
                "max_output_tokens": {"min": 256, "max": 8192, "step": 256},
            },
        ),
        ProviderCatalogEntry(
            provider_id="moonshot",
            label="Moonshot",
            description="Kimi/Moonshot OpenAI-compatible API.",
            api="openai-completions",
            default_base_url="https://api.moonshot.ai/v1",
            auth_env_vars=["EYEX_MOONSHOT_API_KEY", "MOONSHOT_API_KEY"],
            default_models=[
                ProviderModel(id="kimi-k2.6", name="Kimi K2.6", context_window=200000),
                ProviderModel(id="kimi-k2-thinking", name="Kimi K2 Thinking", context_window=200000),
            ],
            option_schema={
                "temperature": {"min": 0, "max": 1, "step": 0.1},
                "max_output_tokens": {"min": 256, "max": 8192, "step": 256},
            },
        ),
        ProviderCatalogEntry(
            provider_id="qwen",
            label="Qwen / DashScope",
            description="Alibaba DashScope OpenAI-compatible endpoint.",
            api="openai-completions",
            default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            auth_env_vars=["EYEX_QWEN_API_KEY", "QWEN_API_KEY", "DASHSCOPE_API_KEY", "MODELSTUDIO_API_KEY"],
            default_models=[
                ProviderModel(id="qwen3.5-plus", name="Qwen 3.5 Plus", context_window=1000000),
                ProviderModel(id="qwen3.5-coder-plus", name="Qwen 3.5 Coder Plus", context_window=1000000),
            ],
            option_schema={
                "temperature": {"min": 0, "max": 1, "step": 0.1},
                "max_output_tokens": {"min": 256, "max": 8192, "step": 256},
            },
        ),
        ProviderCatalogEntry(
            provider_id="zai",
            label="Z.AI / GLM",
            description="Z.AI GLM OpenAI-compatible API.",
            api="openai-completions",
            default_base_url="https://open.bigmodel.cn/api/paas/v4",
            auth_env_vars=["EYEX_ZAI_API_KEY", "ZAI_API_KEY", "GLM_API_KEY"],
            default_models=[ProviderModel(id="glm-5.1", name="GLM 5.1", context_window=200000)],
            option_schema={
                "temperature": {"min": 0, "max": 1, "step": 0.1},
                "max_output_tokens": {"min": 256, "max": 8192, "step": 256},
            },
        ),
        ProviderCatalogEntry(
            provider_id="azure-openai",
            label="Azure OpenAI",
            description="Azure OpenAI v1-compatible endpoint; use deployment name as model.",
            api="openai-completions",
            default_base_url=None,
            auth_env_vars=["EYEX_AZURE_OPENAI_API_KEY", "AZURE_OPENAI_API_KEY"],
            default_models=[],
            option_schema={
                "temperature": {"min": 0, "max": 1, "step": 0.1},
                "max_output_tokens": {"min": 256, "max": 8192, "step": 256},
            },
        ),
        ProviderCatalogEntry(
            provider_id="ollama",
            label="Ollama",
            description="Local Ollama OpenAI-compatible endpoint.",
            api="openai-completions",
            default_base_url="http://127.0.0.1:11434/v1",
            auth_env_vars=["EYEX_OLLAMA_API_KEY", "OLLAMA_API_KEY"],
            auth_optional=True,
            default_models=[ProviderModel(id="llama3.3", name="Llama 3.3")],
            option_schema={
                "temperature": {"min": 0, "max": 1, "step": 0.1},
                "max_output_tokens": {"min": 256, "max": 8192, "step": 256},
            },
        ),
        ProviderCatalogEntry(
            provider_id="custom",
            label="Custom Provider",
            description="Any OpenAI-compatible /v1/chat/completions provider.",
            api="openai-completions",
            default_base_url=None,
            auth_env_vars=["EYEX_COMPATIBLE_API_KEY"],
            default_models=[],
            option_schema={
                "temperature": {"min": 0, "max": 1, "step": 0.1},
                "max_output_tokens": {"min": 256, "max": 8192, "step": 256},
            },
        ),
    ]


def provider_catalog() -> list[ProviderCatalogEntry]:
    configured = _load_provider_catalog_from_yaml()
    return configured or _built_in_provider_catalog()


def provider_payload() -> dict:
    store = _load_store()
    providers = []
    active = _active_selection()
    for entry in provider_catalog():
        stored = store.get(entry.provider_id) or StoredProviderSettings(provider_id=entry.provider_id)
        providers.append(_provider_payload(entry, stored, active=active.get("provider_id") == entry.provider_id))
    return {"active": active, "providers": providers}


def update_provider(provider_id: str, update: ProviderSettingsUpdate) -> dict:
    entry = _require_entry(provider_id)
    store = _load_store()
    stored = store.get(provider_id) or StoredProviderSettings(provider_id=provider_id)
    if update.api is not None:
        if update.api not in _api_options(entry):
            raise ValueError(f"{entry.label} does not support API type: {update.api}")
        stored.api = update.api
    if update.enabled is not None:
        stored.enabled = update.enabled
    if update.api_key is not None:
        key = update.api_key.strip() or None
        set_runtime_provider_api_key(provider_id, key)
        save_provider_api_key(provider_id, key)
        stored.api_key = key if settings.allow_plaintext_provider_keys else None
    if update.base_url is not None:
        stored.base_url = update.base_url.strip() or None
    if update.selected_model is not None:
        stored.selected_model = update.selected_model.strip() or None
    if update.custom_models is not None:
        stored.custom_models = update.custom_models
    if update.model_settings is not None:
        stored.model_settings = _normalize_model_settings(entry, update.model_settings, api=_effective_api(entry, stored))
    store[provider_id] = stored
    _save_store(store)
    return _provider_detail(entry, stored)


def fetch_provider_models(provider_id: str) -> dict:
    entry = _require_entry(provider_id)
    store = _load_store()
    stored = store.get(provider_id) or StoredProviderSettings(provider_id=provider_id)
    try:
        models = _fetch_models(entry, stored)
        if models:
            stored.fetched_models = models
            stored.last_error = None
            stored.connected_at = datetime.now(timezone.utc).isoformat()
            if not stored.selected_model:
                stored.selected_model = models[0].id
        else:
            stored.last_error = "Provider returned no models; use manual model id."
    except Exception as exc:
        stored.last_error = safe_error_message(exc)
        store[provider_id] = stored
        _save_store(store)
        return {"ok": False, **_provider_detail(entry, stored)}
    store[provider_id] = stored
    _save_store(store)
    return {"ok": True, **_provider_detail(entry, stored)}


def activate_provider_model(provider_id: str, model_id: str) -> dict:
    entry = _require_entry(provider_id)
    store = _load_store()
    stored = store.get(provider_id) or StoredProviderSettings(provider_id=provider_id)
    models = _models_for(entry, stored)
    if model_id not in {model.id for model in models}:
        raise ValueError(f"Unknown model for {entry.label}: {model_id}. Fetch models or add it manually first.")
    state = _provider_state(entry, stored)
    if not state["runnable"]:
        raise ValueError(state["status_message"])
    stored.selected_model = model_id
    stored.enabled = True
    store[provider_id] = stored
    _save_store(store)
    profile = build_model_profile(entry, stored, model_id)
    active = set_active_model_profile_object(profile)
    return {"ok": True, "active_model": active.model_dump(), **provider_payload()}


def build_model_profile(entry: ProviderCatalogEntry, stored: StoredProviderSettings, model_id: str | None = None) -> ModelProfile:
    selected = model_id or stored.selected_model or (entry.default_models[0].id if entry.default_models else "custom-model")
    api = _effective_api(entry, stored)
    model_settings = _normalize_model_settings(entry, stored.model_settings, api=api)
    provider = {
        "openai-responses": "openai_responses",
        "openai-completions": "openai_compatible",
        "anthropic-messages": "anthropic_messages",
        "google-gemini": "google_gemini",
        "disabled": "disabled",
    }[api]
    return ModelProfile(
        profile_id=f"provider_{_slug(entry.provider_id)}_{_slug(selected)}",
        label=f"{entry.label} / {selected}",
        provider=provider,
        provider_id=entry.provider_id,
        model_ref=f"{entry.provider_id}/{selected}",
        api=api,
        model=selected,
        base_url=stored.base_url or entry.default_base_url,
        auth_env_vars=entry.auth_env_vars,
        auth_optional=entry.auth_optional,
        response_format="json_schema" if api == "openai-responses" else "json_object",
        reasoning_effort=str(model_settings.get("reasoning_effort") or "low"),
        max_output_tokens=int(model_settings.get("max_output_tokens") or _max_tokens_for(entry, stored, selected)),
        temperature=float(model_settings.get("temperature") if model_settings.get("temperature") is not None else 0.0),
        fallbacks=["local/conservative-local"],
        context_window=_context_window_for(entry, stored, selected),
    )


def _fetch_models(entry: ProviderCatalogEntry, stored: StoredProviderSettings) -> list[ProviderModel]:
    profile = build_model_profile(entry, stored)
    keys = api_keys_for_profile(profile)
    if not keys and not entry.auth_optional:
        raise ValueError(f"Missing API key. Expected one of: {', '.join(entry.auth_env_vars)}")
    base_url = (stored.base_url or entry.default_base_url or "").rstrip("/")
    api = _effective_api(entry, stored)
    if api in {"openai-completions", "openai-responses"}:
        if not base_url and api == "openai-completions":
            raise ValueError("Base URL is required for this provider")
        return _fetch_openai_model_list(base_url, keys[0] if keys else None)
    if api == "anthropic-messages":
        url = f"{base_url}/v1/models"
        headers = {"x-api-key": keys[0], "anthropic-version": "2023-06-01"}
        with httpx.Client(timeout=20) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
        return _models_from_openai_payload(payload)
    if api == "google-gemini":
        url = f"{base_url}/v1beta/models"
        with httpx.Client(timeout=20) as client:
            response = client.get(url, params={"key": keys[0]})
            response.raise_for_status()
            payload = response.json()
        models = []
        for item in payload.get("models", []):
            raw = str(item.get("name", ""))
            model_id = raw.split("/", 1)[1] if raw.startswith("models/") else raw
            methods = item.get("supportedGenerationMethods", [])
            if model_id and (not methods or "generateContent" in methods):
                models.append(ProviderModel(id=model_id, name=item.get("displayName") or model_id))
        return models
    return []


def _provider_detail(entry: ProviderCatalogEntry, stored: StoredProviderSettings) -> dict:
    return _provider_payload(entry, stored)


def _provider_payload(entry: ProviderCatalogEntry, stored: StoredProviderSettings, *, active: bool = False) -> dict:
    models = _models_for(entry, stored)
    state = _provider_state(entry, stored)
    api = _effective_api(entry, stored)
    return {
        **entry.model_dump(),
        "api": api,
        "default_api": entry.api,
        "api_options": _api_options(entry),
        "base_url": state["base_url"],
        "enabled": stored.enabled,
        "selected_model": stored.selected_model or (models[0].id if models else None),
        "models": [model.model_dump() for model in _models_with_state(entry, stored, state["runnable"])],
        "recommended_models": [model.model_dump() for model in _recommended_models(entry)],
        "model_counts": _model_counts(entry, stored),
        "model_settings": _normalize_model_settings(entry, stored.model_settings, api=api),
        "option_schema": _option_schema_for_api(entry, api),
        "api_key_configured": state["api_key_configured"],
        "api_key_masked": _mask_secret(state["explicit_keys"][0] if state["explicit_keys"] else None),
        "credential_status": state["credential_status"],
        "connection_status": state["connection_status"],
        "runnable": state["runnable"],
        "status_message": state["status_message"],
        "last_error": stored.last_error,
        "connected_at": stored.connected_at,
        "active": active,
    }


def _models_for(entry: ProviderCatalogEntry, stored: StoredProviderSettings) -> list[ProviderModel]:
    merged: dict[str, ProviderModel] = {}
    for model in [*stored.fetched_models, *stored.custom_models]:
        merged.setdefault(model.id, model)
    return list(merged.values())


def _known_models_for_metadata(entry: ProviderCatalogEntry, stored: StoredProviderSettings) -> list[ProviderModel]:
    merged: dict[str, ProviderModel] = {}
    for model in [*stored.fetched_models, *stored.custom_models, *entry.default_models]:
        merged.setdefault(model.id, model)
    return list(merged.values())


def _models_with_state(entry: ProviderCatalogEntry, stored: StoredProviderSettings, runnable: bool) -> list[ProviderModel]:
    merged: dict[str, ProviderModel] = {}
    for source, models in (
        ("fetched", stored.fetched_models),
        ("custom", stored.custom_models),
    ):
        for model in models:
            merged.setdefault(model.id, model.model_copy(update={"source": source, "runnable": runnable}))
    return list(merged.values())


def _recommended_models(entry: ProviderCatalogEntry) -> list[ProviderModel]:
    return [
        model.model_copy(update={"source": "preset", "runnable": False})
        for model in entry.default_models
    ]


def _model_counts(entry: ProviderCatalogEntry, stored: StoredProviderSettings) -> dict[str, int]:
    return {
        "fetched": len(stored.fetched_models),
        "custom": len(stored.custom_models),
        "preset": len(entry.default_models),
    }


def _provider_state(entry: ProviderCatalogEntry, stored: StoredProviderSettings) -> dict:
    explicit_keys = explicit_api_keys_for_profile(build_model_profile(entry, stored))
    base_url = stored.base_url or entry.default_base_url
    api = _effective_api(entry, stored)
    api_key_configured = bool(explicit_keys)
    credential_ready = entry.auth_optional or api_key_configured or api == "disabled"
    base_url_ready = bool(base_url) or api == "disabled"
    runnable = stored.enabled and credential_ready and base_url_ready
    if not stored.enabled:
        credential_status = "disabled"
        status_message = f"{entry.label} 已关闭，不会参与抽取。"
    elif not base_url_ready:
        credential_status = "missing_base_url"
        status_message = f"{entry.label} 需要先填写 Base URL。"
    elif not credential_ready:
        credential_status = "missing_api_key"
        status_message = f"{entry.label} 需要先配置 API Key：{', '.join(entry.auth_env_vars) or 'provider API key'}。"
    elif entry.auth_optional and not api_key_configured:
        credential_status = "optional"
        status_message = f"{entry.label} 可在无 API Key 的本地模式下使用。"
    else:
        credential_status = "configured"
        status_message = f"{entry.label} 已具备运行条件。"
    if stored.last_error:
        connection_status = "error"
    elif stored.connected_at:
        connection_status = "verified"
    else:
        connection_status = "not_tested"
    return {
        "base_url": base_url,
        "explicit_keys": explicit_keys,
        "api_key_configured": api_key_configured,
        "credential_status": credential_status,
        "connection_status": connection_status,
        "runnable": runnable,
        "status_message": status_message,
    }


def _api_options(entry: ProviderCatalogEntry) -> list[ProviderApi]:
    return entry.api_options or [entry.api]


def _effective_api(entry: ProviderCatalogEntry, stored: StoredProviderSettings) -> ProviderApi:
    if stored.api and stored.api in _api_options(entry):
        return stored.api
    return entry.api


def _option_schema_for_api(entry: ProviderCatalogEntry, api: ProviderApi) -> dict[str, Any]:
    if entry.provider_id == "openai" and api == "openai-completions":
        return {
            "temperature": {"min": 0, "max": 1, "step": 0.1},
            "max_output_tokens": {"min": 256, "max": 8192, "step": 256},
        }
    return entry.option_schema


def _normalize_model_settings(entry: ProviderCatalogEntry, raw: dict[str, Any] | None, *, api: ProviderApi | None = None) -> dict[str, Any]:
    raw = raw or {}
    normalized: dict[str, Any] = {}
    option_schema = _option_schema_for_api(entry, api or entry.api)
    if "reasoning_effort" in option_schema:
        choices = [str(item) for item in option_schema["reasoning_effort"]]
        effort = str(raw.get("reasoning_effort") or "low")
        normalized["reasoning_effort"] = effort if effort in choices else "low"
    if "temperature" in option_schema:
        spec = option_schema["temperature"]
        normalized["temperature"] = _bounded_float(
            raw.get("temperature"),
            default=0.0,
            minimum=float(spec.get("min", 0.0)),
            maximum=float(spec.get("max", 1.0)),
        )
    if "max_output_tokens" in option_schema:
        spec = option_schema["max_output_tokens"]
        normalized["max_output_tokens"] = _bounded_int(
            raw.get("max_output_tokens"),
            default=4096,
            minimum=int(spec.get("min", 256)),
            maximum=int(spec.get("max", 8192)),
        )
    return normalized


def _bounded_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


def _fetch_openai_model_list(base_url: str, api_key: str | None) -> list[ProviderModel]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    urls = _openai_model_list_urls(base_url)
    last_error: Exception | None = None
    with httpx.Client(timeout=20) as client:
        for index, url in enumerate(urls):
            try:
                response = client.get(url, headers=headers)
                response.raise_for_status()
                models = _models_from_openai_payload(response.json())
                if models or index == len(urls) - 1:
                    return models
            except Exception as exc:
                last_error = exc
                if index == len(urls) - 1 or not _can_try_next_model_list_url(exc):
                    raise
    if last_error:
        raise last_error
    return []


def _openai_model_list_urls(base_url: str) -> list[str]:
    if not base_url:
        return ["https://api.openai.com/v1/models"]
    base = base_url.rstrip("/")
    candidates = [f"{base}/models"]
    if not base.endswith("/v1"):
        candidates.append(f"{base}/v1/models")
    return list(dict.fromkeys(candidates))


def _can_try_next_model_list_url(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {400, 404, 405}
    return isinstance(exc, (ValueError, json.JSONDecodeError))


def _models_from_openai_payload(payload: dict) -> list[ProviderModel]:
    if isinstance(payload, list):
        data = payload
    elif isinstance(payload, dict):
        data = payload.get("data", payload.get("models", []))
    else:
        data = []
    models: dict[str, ProviderModel] = {}
    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                model_id = item.strip()
                name = model_id
            elif isinstance(item, dict):
                model_id = str(item.get("id") or item.get("model") or item.get("model_id") or item.get("name") or "")
                name = str(item.get("display_name") or item.get("name") or model_id)
            else:
                continue
            if not model_id:
                continue
            models.setdefault(model_id, ProviderModel(id=model_id, name=name))
    return list(models.values())


def _active_selection() -> dict:
    path = settings.storage_dir / "model_selection.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    dynamic = payload.get("dynamic_profile")
    if isinstance(dynamic, dict):
        return {
            "provider_id": dynamic.get("provider_id"),
            "model_ref": dynamic.get("model_ref"),
            "model": dynamic.get("model"),
        }
    model_ref = payload.get("model_ref")
    return {
        "provider_id": str(model_ref).split("/", 1)[0] if model_ref else None,
        "model_ref": model_ref,
        "model": payload.get("model"),
    }


def _load_store() -> dict[str, StoredProviderSettings]:
    path = _store_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not settings.allow_plaintext_provider_keys:
        for value in payload.values():
            if isinstance(value, dict):
                value["api_key"] = None
    return {
        key: StoredProviderSettings.model_validate({"provider_id": key, **value})
        for key, value in payload.items()
        if isinstance(value, dict)
    }


def _save_store(store: dict[str, StoredProviderSettings]) -> None:
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    payload = {}
    for key, value in store.items():
        item = value.model_dump()
        if not settings.allow_plaintext_provider_keys:
            item["api_key"] = None
        payload[key] = item
    _store_path().write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _store_path() -> Path:
    return settings.storage_dir / "provider_settings.json"


def _load_provider_catalog_from_yaml() -> list[ProviderCatalogEntry]:
    directory = settings.config_dir / "model_providers"
    if not directory.exists():
        return []
    entries: list[ProviderCatalogEntry] = []
    for path in sorted(directory.glob("*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            items = raw if isinstance(raw, list) else raw.get("providers", [])
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict):
                    entries.append(ProviderCatalogEntry.model_validate(item))
        except Exception:
            continue
    return entries


def _require_entry(provider_id: str) -> ProviderCatalogEntry:
    for entry in provider_catalog():
        if entry.provider_id == provider_id:
            return entry
    raise ValueError(f"Unknown provider: {provider_id}")


def _mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "********"
    return f"{value[:4]}...{value[-4:]}"


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower() or "model"


def _max_tokens_for(entry: ProviderCatalogEntry, stored: StoredProviderSettings, model_id: str) -> int:
    for model in _known_models_for_metadata(entry, stored):
        if model.id == model_id and model.max_tokens:
            return min(model.max_tokens, 8192)
    return 4096


def _context_window_for(entry: ProviderCatalogEntry, stored: StoredProviderSettings, model_id: str) -> int | None:
    for model in _known_models_for_metadata(entry, stored):
        if model.id == model_id:
            return model.context_window
    return None
