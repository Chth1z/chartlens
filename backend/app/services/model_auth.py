from __future__ import annotations

import os
import re
import json
from functools import lru_cache
from pathlib import Path

from app.core.settings import settings
from app.domain.models import ModelProfile
from app.services.secret_store import load_provider_api_key

_RUNTIME_PROVIDER_API_KEYS: dict[str, str] = {}


@lru_cache(maxsize=1)
def _dotenv_values() -> dict[str, str]:
    path = Path(".env")
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def env_value(name: str) -> str | None:
    value = os.getenv(name)
    if value:
        return value
    value = _dotenv_values().get(name)
    return value or _settings_value(name)


def auth_env_names(profile: ModelProfile) -> list[str]:
    provider_id = profile.provider_id or profile.profile_id
    names = [
        f"OPENCLAW_LIVE_{_env_provider(provider_id)}_KEY",
        *profile.auth_env_vars,
    ]
    if profile.api_key_env:
        names.append(profile.api_key_env)
    names.extend(
        [
            f"{_env_provider(provider_id)}_API_KEYS",
            f"{_env_provider(provider_id)}_API_KEY",
        ]
    )
    names.extend(f"{_env_provider(provider_id)}_API_KEY_{index}" for index in range(1, 10))
    return list(dict.fromkeys(names))


def explicit_api_keys_for_profile(profile: ModelProfile) -> list[str]:
    keys: list[str] = []
    if profile.api_key_value:
        keys.append(profile.api_key_value)
    stored = _stored_provider_api_key(profile.provider_id)
    if stored and stored not in keys:
        keys.append(stored)
    for name in auth_env_names(profile):
        raw = env_value(name)
        if not raw:
            continue
        for value in re.split(r"[;,]", raw):
            key = value.strip()
            if key and key not in keys:
                keys.append(key)
    return keys


def api_keys_for_profile(profile: ModelProfile) -> list[str]:
    keys = explicit_api_keys_for_profile(profile)
    if profile.auth_optional and not keys:
        keys.append("eyex-local")
    return keys


def auth_configured_for_profile(profile: ModelProfile) -> bool:
    return profile.auth_optional or bool(api_keys_for_profile(profile))


def env_state_for_profiles(profiles: list[ModelProfile]) -> dict[str, dict]:
    state: dict[str, dict] = {}
    for profile in profiles:
        provider_id = profile.provider_id or profile.profile_id
        names = auth_env_names(profile)
        state[provider_id] = {
            "configured": auth_configured_for_profile(profile),
            "auth_optional": profile.auth_optional,
            "env_vars": names,
        }
    return state


def _env_provider(provider_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", provider_id).upper()


def _settings_value(env_name: str) -> str | None:
    mapping = {
        "EYEX_OPENAI_API_KEY": settings.openai_api_key,
        "OPENAI_API_KEY": settings.openai_api_key,
        "EYEX_DEEPSEEK_API_KEY": settings.deepseek_api_key,
        "DEEPSEEK_API_KEY": settings.deepseek_api_key,
        "EYEX_COMPATIBLE_API_KEY": settings.compatible_api_key,
    }
    return mapping.get(env_name)


def _stored_provider_api_key(provider_id: str | None) -> str | None:
    if not provider_id:
        return None
    runtime_key = _RUNTIME_PROVIDER_API_KEYS.get(provider_id)
    if runtime_key:
        return runtime_key
    encrypted_key = load_provider_api_key(provider_id)
    if encrypted_key:
        return encrypted_key
    if not settings.allow_plaintext_provider_keys:
        return None
    path = settings.storage_dir / "provider_settings.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    provider_payload = payload.get(provider_id)
    if not isinstance(provider_payload, dict):
        return None
    value = provider_payload.get("api_key")
    return str(value) if value else None


def set_runtime_provider_api_key(provider_id: str, api_key: str | None) -> None:
    if api_key:
        _RUNTIME_PROVIDER_API_KEYS[provider_id] = api_key
    else:
        _RUNTIME_PROVIDER_API_KEYS.pop(provider_id, None)
