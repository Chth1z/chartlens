from __future__ import annotations

import json
import re
from pathlib import Path

from app.core.settings import settings

from app.services.model_providers.types import StoredProviderSettings


def _store_path() -> Path:
    return settings.storage_dir / "provider_settings.json"


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


def _mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "********"
    return f"{value[:4]}...{value[-4:]}"


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower() or "model"
