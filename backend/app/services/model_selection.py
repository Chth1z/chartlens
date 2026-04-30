from __future__ import annotations

import json
from pathlib import Path

from typing import Any

from pydantic import BaseModel

from app.core.config_loader import list_model_profiles, load_model_profile
from app.core.settings import settings
from app.domain.models import ModelProfile
from app.services.model_auth import auth_configured_for_profile, env_state_for_profiles


class ActiveModelSelection(BaseModel):
    profile_id: str
    provider: str
    model: str
    model_ref: str
    base_url: str | None = None
    fallbacks: list[str] = []
    dynamic_profile: dict[str, Any] | None = None


def _selection_path() -> Path:
    return settings.storage_dir / "model_selection.json"


def get_active_model_profile() -> ModelProfile:
    path = _selection_path()
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            dynamic_profile = payload.get("dynamic_profile")
            if isinstance(dynamic_profile, dict):
                return ModelProfile.model_validate(dynamic_profile)
            selector = str(payload.get("profile_id") or payload.get("model_ref") or settings.model_profile)
            return resolve_model_profile(selector)
        except Exception:
            pass
    return resolve_model_profile(settings.model_profile)


def resolve_model_profile(selector: str) -> ModelProfile:
    selector = selector.strip()
    if not selector:
        return load_model_profile(settings.model_profile)
    for profile in list_model_profiles():
        if selector in {profile.profile_id, _model_ref(profile)}:
            return _effective_profile(profile)
    raise ValueError(f"Unknown model profile or model ref: {selector}")


def resolve_model_chain(primary: ModelProfile | None = None) -> list[ModelProfile]:
    first = primary or get_active_model_profile()
    chain: list[ModelProfile] = [first]
    seen: set[str] = {_model_ref(first)}
    selectors = first.fallbacks
    for selector in selectors:
        try:
            profile = resolve_model_profile(selector)
        except ValueError:
            continue
        model_ref = _model_ref(profile)
        if model_ref in seen:
            continue
        seen.add(model_ref)
        chain.append(profile)
    return chain or [first]


def set_active_model_profile(profile_id: str) -> ActiveModelSelection:
    profile = resolve_model_profile(profile_id)
    return set_active_model_profile_object(profile)


def set_active_model_profile_object(profile: ModelProfile) -> ActiveModelSelection:
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    payload = ActiveModelSelection(
        profile_id=profile.profile_id,
        provider=profile.provider,
        model=profile.model,
        model_ref=_model_ref(profile),
        base_url=profile.base_url,
        fallbacks=profile.fallbacks,
        dynamic_profile=profile.model_dump(),
    )
    _selection_path().write_text(payload.model_dump_json(indent=2), encoding="utf-8")
    return payload


def model_profiles_payload() -> dict:
    active = get_active_model_profile()
    profiles: list[dict] = []
    loaded_profiles = [_effective_profile(profile) for profile in list_model_profiles()]
    for profile in list_model_profiles():
        effective = _effective_profile(profile)
        payload = effective.model_dump()
        payload["model_ref"] = _model_ref(effective)
        payload["auth_configured"] = auth_configured_for_profile(effective)
        profiles.append(payload)
    if active.profile_id not in {profile["profile_id"] for profile in profiles}:
        active_payload = active.model_dump()
        active_payload["model_ref"] = _model_ref(active)
        active_payload["auth_configured"] = auth_configured_for_profile(active)
        profiles.insert(0, active_payload)
    return {
        "active_profile_id": active.profile_id,
        "active_model_ref": _model_ref(active),
        "fallbacks": active.fallbacks,
        "resolved_chain": [_model_ref(profile) for profile in resolve_model_chain(active)],
        "profiles": profiles,
        "env": {
            "openai_api_key_configured": bool(settings.openai_api_key),
            "deepseek_api_key_configured": bool(settings.deepseek_api_key),
            "compatible_api_key_configured": bool(settings.compatible_api_key),
            "compatible_base_url_configured": bool(settings.compatible_base_url),
            "compatible_model_configured": bool(settings.compatible_model),
            "providers": env_state_for_profiles(loaded_profiles),
        },
    }


def _effective_profile(profile: ModelProfile) -> ModelProfile:
    data = profile.model_dump()
    if profile.profile_id.startswith("deepseek") and settings.deepseek_base_url:
        data["base_url"] = settings.deepseek_base_url
    if profile.profile_id == "openai_compatible_custom":
        model = settings.compatible_model or profile.model
        data["base_url"] = settings.compatible_base_url or profile.base_url
        data["model"] = model
        data["model_ref"] = f"{profile.provider_id or 'custom'}/{model}"
    return ModelProfile.model_validate(data)


def _model_ref(profile: ModelProfile) -> str:
    return profile.model_ref or f"{profile.provider_id or profile.profile_id}/{profile.model}"
