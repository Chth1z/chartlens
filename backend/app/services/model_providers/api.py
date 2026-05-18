from __future__ import annotations

from typing import Any

from app.core.settings import settings
from app.domain.models import ModelProfile
from app.services.model_auth import set_runtime_provider_api_key
from app.services.model_selection import set_active_model_profile_object
from app.services.secret_store import save_provider_api_key

from app.services.model_providers.catalog import _require_entry, provider_catalog
from app.services.model_providers.discovery import fetch_provider_models
from app.services.model_providers.settings_store import (
    _load_store,
    _mask_secret,
    _save_store,
    _slug,
)
from app.services.model_providers.types import (
    ProviderApi,
    ProviderCatalogEntry,
    ProviderModel,
    ProviderSettingsUpdate,
    StoredProviderSettings,
)

import json


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
    import app.services.model_providers as _pkg

    explicit_keys = _pkg.explicit_api_keys_for_profile(build_model_profile(entry, stored))
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
