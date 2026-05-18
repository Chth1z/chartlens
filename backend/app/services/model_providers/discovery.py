from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx

from app.services.model_auth import api_keys_for_profile
from app.services.safe_errors import safe_error_message

from app.services.model_providers.catalog import _require_entry
from app.services.model_providers.settings_store import _load_store, _save_store
from app.services.model_providers.types import ProviderCatalogEntry, ProviderModel, StoredProviderSettings


def fetch_provider_models(provider_id: str) -> dict:
    import app.services.model_providers as _pkg
    from app.services.model_providers.api import _provider_detail

    entry = _require_entry(provider_id)
    store = _load_store()
    stored = store.get(provider_id) or StoredProviderSettings(provider_id=provider_id)
    try:
        models = _pkg._fetch_models(entry, stored)
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


def _fetch_models(entry: ProviderCatalogEntry, stored: StoredProviderSettings) -> list[ProviderModel]:
    from app.services.model_providers.api import _effective_api, build_model_profile

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
