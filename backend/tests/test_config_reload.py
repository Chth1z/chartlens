"""Tests for config hot-reload."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config_loader import (
    invalidate_config_cache,
    load_document_profile,
    load_extraction_schema,
)
from app.main import app

client = TestClient(app)


def test_invalidate_config_cache_clears_all():
    """invalidate_config_cache clears lru_cache entries."""
    # Warm the caches
    load_document_profile()
    load_extraction_schema()

    # Verify caches are populated
    assert load_document_profile.cache_info().currsize > 0
    assert load_extraction_schema.cache_info().currsize > 0

    # Invalidate
    count = invalidate_config_cache()
    assert count == 6  # 6 cached functions

    # Verify caches are empty
    assert load_document_profile.cache_info().currsize == 0
    assert load_extraction_schema.cache_info().currsize == 0


def test_reload_config_endpoint():
    """POST /api/system/reload-config returns success."""
    response = client.post("/api/system/reload-config")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["affected_count"] == 6
    assert "cache" in data["message"].lower()


def test_config_still_loads_after_invalidation():
    """Config loads correctly after cache invalidation."""
    invalidate_config_cache()
    profile = load_document_profile()
    assert profile.profile_id == "medical_inpatient_zh"
