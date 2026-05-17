from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.settings import settings
from app.main import app
from app.api import routes as api_routes
from app.services.runtime_status import build_ocr_runtime_status, sidecar_health_url


def test_sidecar_health_url_rewrites_extract_endpoint() -> None:
    assert sidecar_health_url("http://127.0.0.1:8765/extract") == "http://127.0.0.1:8765/health"
    assert sidecar_health_url("http://127.0.0.1:8765/ocr/extract") == "http://127.0.0.1:8765/health"


def test_ocr_runtime_status_reports_sidecar_not_running(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ocr_document_ai_url", "http://127.0.0.1:8765/extract")

    def failing_get_json(url: str, timeout: float) -> dict:
        raise RuntimeError("connection refused")

    status = build_ocr_runtime_status(http_get_json=failing_get_json)

    assert status["ready"] is False
    assert status["status"] == "not_running"
    assert "OCR sidecar" in status["summary"]
    assert status["actions"][0]["command"] == ".\\start.cmd"


def test_ocr_runtime_status_reports_missing_directml_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ocr_document_ai_url", "http://127.0.0.1:8765/extract")

    def fake_get_json(url: str, timeout: float) -> dict:
        return {
            "ok": True,
            "api_contract_version": "eyex-ocr-sidecar-v2",
            "ocr_profile": {"profile_id": "windows_radeon_balanced"},
            "pipeline_stages": ["preprocess", "pp_structure_v3", "pp_ocr_v5", "merge"],
            "strong_pipeline_readiness": {
                "ready": False,
                "stages": {
                    "pp_structure_v3": {"ready": True, "engine_id": "paddle_structure_v3", "reason": ""},
                    "pp_ocr_v5": {
                        "ready": False,
                        "engine_id": "pp_ocr_v5_onnx_directml",
                        "reason": "DmlExecutionProvider unavailable",
                    },
                },
            },
        }

    status = build_ocr_runtime_status(http_get_json=fake_get_json)

    assert status["ready"] is False
    assert status["status"] == "not_ready"
    assert "PP-OCRv5" in status["summary"]
    assert any(action["command"] == ".\\install-ocr.cmd" for action in status["actions"])


def test_ocr_runtime_status_reports_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ocr_document_ai_url", "http://127.0.0.1:8765/extract")

    def fake_get_json(url: str, timeout: float) -> dict:
        return {
            "ok": True,
            "api_contract_version": "eyex-ocr-sidecar-v2",
            "ocr_profile": {
                "profile_id": "windows_radeon_balanced",
                "merge_policy_version": "ocr-canonical-layout-v3",
            },
            "device": {"resolved": "directml", "accelerator": "directml", "available_accelerators": ["directml"]},
            "pipeline_stages": ["preprocess", "pp_structure_v3", "pp_ocr_v5", "merge"],
            "strong_pipeline_readiness": {"ready": True, "stages": {}},
        }

    status = build_ocr_runtime_status(http_get_json=fake_get_json)

    assert status["ready"] is True
    assert status["status"] == "ready"
    assert status["summary"] == "OCR 强准确链路已就绪"


def test_ocr_runtime_status_rejects_stale_sidecar_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ocr_profile", "windows_radeon_balanced")
    monkeypatch.setattr(settings, "ocr_document_ai_url", "http://127.0.0.1:8765/extract")

    def fake_get_json(url: str, timeout: float) -> dict:
        return {
            "ok": True,
            "ocr_profile": {"profile_id": "windows_radeon_balanced"},
            "device": {"resolved": "directml", "accelerator": "directml", "available_accelerators": ["directml"]},
            "strong_pipeline_readiness": {"ready": True, "stages": {}},
        }

    status = build_ocr_runtime_status(http_get_json=fake_get_json)

    assert status["ready"] is False
    assert status["status"] == "not_ready"
    assert any(check["key"] == "sidecar_api_contract" for check in status["checks"])
    assert "restart" in " ".join(status["details"]).lower()


def test_ocr_runtime_status_rejects_stale_sidecar_layout_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ocr_profile", "windows_radeon_balanced")
    monkeypatch.setattr(settings, "ocr_document_ai_url", "http://127.0.0.1:8765/extract")

    def fake_get_json(url: str, timeout: float) -> dict:
        return {
            "ok": True,
            "api_contract_version": "eyex-ocr-sidecar-v2",
            "ocr_profile": {
                "profile_id": "windows_radeon_balanced",
                "merge_policy_version": "ocr-canonical-layout-v2",
            },
            "device": {"resolved": "directml", "accelerator": "directml", "available_accelerators": ["directml"]},
            "strong_pipeline_readiness": {"ready": True, "stages": {}},
        }

    status = build_ocr_runtime_status(http_get_json=fake_get_json)

    assert status["ready"] is False
    assert status["status"] == "not_ready"
    assert any(check["key"] == "layout_policy" and check["ready"] is False for check in status["checks"])
    assert "ocr-canonical-layout-v3" in " ".join(status["details"])
    assert any(action["command"] == ".\\stop.cmd" for action in status["actions"])


def test_ocr_runtime_status_rejects_sidecar_profile_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ocr_profile", "cuda_paddle")
    monkeypatch.setattr(settings, "ocr_document_ai_url", "http://127.0.0.1:8765/extract")

    def fake_get_json(url: str, timeout: float) -> dict:
        return {
            "ok": True,
            "api_contract_version": "eyex-ocr-sidecar-v2",
            "ocr_profile": {"profile_id": "windows_radeon_balanced"},
            "pipeline_stages": ["preprocess", "pp_structure_v3", "pp_ocr_v5", "merge"],
            "strong_pipeline_readiness": {"ready": True, "stages": {}},
        }

    status = build_ocr_runtime_status(http_get_json=fake_get_json)

    assert status["ready"] is False
    assert status["status"] == "not_ready"
    assert "OCR profile mismatch" in status["details"][0]
    assert "cuda_paddle" in status["details"][0]
    assert "windows_radeon_balanced" in status["details"][0]


def test_ocr_runtime_status_rejects_cpu_accelerator_for_gpu_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ocr_profile", "cuda_paddle")
    monkeypatch.setattr(settings, "ocr_document_ai_url", "http://127.0.0.1:8765/extract")

    def fake_get_json(url: str, timeout: float) -> dict:
        return {
            "ok": True,
            "api_contract_version": "eyex-ocr-sidecar-v2",
            "ocr_profile": {"profile_id": "cuda_paddle"},
            "device": {"resolved": "cpu", "accelerator": "cpu"},
            "pipeline_stages": ["preprocess", "pp_structure_v3", "pp_ocr_v5", "merge"],
            "strong_pipeline_readiness": {
                "ready": True,
                "stages": {
                    "pp_structure_v3": {"ready": True, "engine_id": "paddle_structure_v3", "reason": ""},
                    "pp_ocr_v5": {"ready": True, "engine_id": "pp_ocr_v5_paddle", "reason": ""},
                },
            },
        }

    status = build_ocr_runtime_status(http_get_json=fake_get_json)

    assert status["ready"] is False
    assert status["status"] == "not_ready"
    assert any(check["key"] == "gpu_accelerator" and check["ready"] is False for check in status["checks"])
    assert "cpu" in " ".join(status["details"])


def test_runtime_settings_endpoint_includes_service_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        api_routes,
        "build_runtime_services",
        lambda: {"ocr": {"key": "ocr", "label": "智能文档 OCR", "ready": False, "status": "not_running"}},
    )

    response = TestClient(app).get("/api/settings/runtime")

    assert response.status_code == 200
    payload = response.json()
    assert payload["runtime_settings"]["services"]["ocr"]["status"] == "not_running"
