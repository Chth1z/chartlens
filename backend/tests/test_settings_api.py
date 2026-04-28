from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_settings_status_exposes_config_paths_and_runtime_profiles():
    system = client.get("/api/settings/system")
    dictionary = client.get("/api/settings/field-dictionary")
    runtime = client.get("/api/settings/runtime")

    assert system.status_code == 200
    assert dictionary.status_code == 200
    assert runtime.status_code == 200
    assert system.json()["system_config"]["version"]
    assert system.json()["system_config"]["path"].endswith("system_config.yaml")
    assert dictionary.json()["field_dictionary"]["field_count"] > 0
    assert runtime.json()["runtime_settings"]["database_url"].startswith("sqlite")
    assert "CHARTLENS_OCR_PROFILE" in runtime.json()["restart_required_hints"]


def test_settings_validate_reports_duplicate_field_keys():
    response = client.post(
        "/api/settings/validate",
        json={
            "field_dictionary_yaml": """
version: test
fields:
  - key: gender
    label: 性别
    export_header: 性别
    allowed_codes: ["1", "2"]
  - key: gender
    label: 重复性别
    export_header: 重复性别
    allowed_codes: ["1", "2"]
""",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert any("Duplicate field key: gender" in item for item in payload["validation_errors"])


def test_settings_validate_reports_missing_active_profiles(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ocr_profile", "missing_ocr_profile")
    response = client.post("/api/settings/validate", json={})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert any("CHARTLENS_OCR_PROFILE" in item for item in payload["validation_errors"])
