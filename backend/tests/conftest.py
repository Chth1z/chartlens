from __future__ import annotations

import pytest

from app.core.config import settings


@pytest.fixture(autouse=True)
def isolate_online_model_auth(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "openai_auth_mode", "disabled", raising=False)
    monkeypatch.setattr(settings, "chatgpt_token_cache_path", tmp_path / "chatgpt_tokens.json", raising=False)
    monkeypatch.setattr(settings, "sync_pipeline", True)
