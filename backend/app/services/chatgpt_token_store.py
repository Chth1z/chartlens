from __future__ import annotations

import base64
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings
from app.services.auth import AuthUser

_LOCK = threading.Lock()


def save_chatgpt_tokens(token_payload: dict[str, Any], user: AuthUser) -> dict[str, Any]:
    """Persist ChatGPT/Codex OAuth tokens locally.

    The cache contains bearer credentials and must be treated like a password.
    """
    now = int(time.time())
    existing = load_chatgpt_tokens() or {}
    existing_tokens = existing.get("tokens") if isinstance(existing.get("tokens"), dict) else {}
    tokens = dict(existing_tokens)
    for key in ("access_token", "refresh_token", "id_token", "scope", "token_type"):
        value = token_payload.get(key)
        if value:
            tokens[key] = value

    expires_at = token_payload.get("expires_at")
    if not expires_at and token_payload.get("expires_in"):
        expires_at = now + int(token_payload["expires_in"])
    if expires_at:
        tokens["expires_at"] = int(float(expires_at))

    cache = {
        "auth_mode": "chatgpt_codex",
        "updated_at": now,
        "user": {"sub": user.sub, "email": user.email, "name": user.name},
        "tokens": tokens,
    }
    _write_cache(cache)
    return cache


def load_chatgpt_tokens() -> dict[str, Any] | None:
    path = _cache_path()
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    tokens = data.get("tokens")
    if not isinstance(tokens, dict):
        return None
    return data


def has_chatgpt_model_auth() -> bool:
    cache = load_chatgpt_tokens()
    if cache is None:
        return False
    tokens = cache.get("tokens") or {}
    return bool(tokens.get("access_token") or tokens.get("refresh_token"))


def get_chatgpt_access_token() -> str:
    cache = load_chatgpt_tokens()
    if cache is None:
        raise RuntimeError("ChatGPT/Codex login token cache is missing")
    tokens = cache.get("tokens") or {}
    access_token = str(tokens.get("access_token") or "")
    if access_token and not _is_near_expiry(tokens):
        return access_token
    refreshed = refresh_chatgpt_tokens()
    refreshed_access_token = str((refreshed.get("tokens") or {}).get("access_token") or "")
    if not refreshed_access_token:
        raise RuntimeError("ChatGPT/Codex token refresh did not return access_token")
    return refreshed_access_token


def refresh_chatgpt_tokens() -> dict[str, Any]:
    with _LOCK:
        cache = load_chatgpt_tokens()
        if cache is None:
            raise RuntimeError("ChatGPT/Codex login token cache is missing")
        tokens = cache.get("tokens") or {}
        refresh_token = str(tokens.get("refresh_token") or "")
        if not refresh_token:
            raise RuntimeError("ChatGPT/Codex refresh_token is missing; please sign in again")

        response = httpx.post(
            settings.chatgpt_oauth_token_url,
            data={
                "grant_type": "refresh_token",
                "client_id": settings.chatgpt_oauth_client_id,
                "refresh_token": refresh_token,
            },
            headers={"Accept": "application/json"},
            timeout=20,
        )
        response.raise_for_status()
        user_payload = cache.get("user") if isinstance(cache.get("user"), dict) else {}
        user = AuthUser(
            sub=str(user_payload.get("sub") or "chatgpt-user"),
            email=user_payload.get("email"),
            name=user_payload.get("name"),
        )
        return save_chatgpt_tokens(response.json(), user)


def clear_chatgpt_tokens() -> None:
    try:
        _cache_path().unlink(missing_ok=True)
    except OSError:
        return


def _is_near_expiry(tokens: dict[str, Any]) -> bool:
    expires_at = tokens.get("expires_at")
    if expires_at is None:
        expires_at = _jwt_exp(str(tokens.get("access_token") or ""))
    if not expires_at:
        return False
    return int(float(expires_at)) - int(time.time()) <= settings.chatgpt_token_refresh_margin_seconds


def _jwt_exp(token: str) -> int | None:
    payload = _decode_jwt_payload(token)
    exp = payload.get("exp")
    return int(float(exp)) if exp else None


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, json.JSONDecodeError):
        return {}


def _write_cache(cache: dict[str, Any]) -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _cache_path() -> Path:
    return Path(settings.chatgpt_token_cache_path)
