from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api import routes
from app.core import database
from app.core.database import CaseRecord, FieldResultRecord, SessionLocal, json_loads
from app.core.settings import settings
from app.domain.models import DocumentIR, DocumentIRBlock, ValidatedFieldResult
from app.main import app
from app.services.model_auth import set_runtime_provider_api_key
from app.services import model_providers
from app.services.pipeline import process_case


def test_non_loopback_browser_origin_is_rejected():
    client = TestClient(app)

    response = client.post(
        "/api/settings/validate",
        headers={"origin": "http://192.168.1.20:5173"},
        json={},
    )

    assert response.status_code == 403


def test_upload_rejects_unsupported_file_type(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_dir", tmp_path)
    monkeypatch.setattr(settings, "auto_process_uploads", False)
    client = TestClient(app)

    response = client.post(
        "/api/cases",
        files={"file": ("payload.exe", b"not a case", "application/octet-stream")},
    )

    assert response.status_code == 415


def test_upload_rejects_files_over_configured_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_dir", tmp_path)
    monkeypatch.setattr(settings, "auto_process_uploads", False)
    monkeypatch.setattr(settings, "max_upload_bytes", 8, raising=False)
    client = TestClient(app)

    response = client.post(
        "/api/cases",
        files={"file": ("case.txt", b"123456789", "text/plain")},
    )

    assert response.status_code == 413


def test_upload_rejects_when_processing_queue_is_full(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_dir", tmp_path)
    monkeypatch.setattr(settings, "auto_process_uploads", True)
    monkeypatch.setattr(routes, "enqueue_case", lambda case_id: False)
    client = TestClient(app)

    response = client.post(
        "/api/cases",
        files={"file": ("case.txt", b"basic text", "text/plain")},
    )

    assert response.status_code == 429


def test_provider_api_key_is_not_persisted_as_plaintext(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_dir", tmp_path)
    monkeypatch.setattr(settings, "allow_plaintext_provider_keys", False, raising=False)
    client = TestClient(app)

    response = client.patch(
        "/api/model-providers/custom",
        json={
            "api_key": "test-key-secret",
            "base_url": "http://127.0.0.1:9999/v1",
            "selected_model": "demo-model",
            "custom_models": [{"id": "demo-model", "name": "Demo Model"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["provider"]["api_key_configured"] is True
    store_text = (tmp_path / "provider_settings.json").read_text(encoding="utf-8")
    assert "test-key-secret" not in store_text


def test_provider_api_key_survives_backend_restart_without_plaintext(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_dir", tmp_path)
    monkeypatch.setattr(settings, "allow_plaintext_provider_keys", False, raising=False)
    client = TestClient(app)

    response = client.patch(
        "/api/model-providers/custom",
        json={
            "api_key": "restart-safe-key",
            "base_url": "http://127.0.0.1:9999/v1",
            "selected_model": "demo-model",
            "custom_models": [{"id": "demo-model", "name": "Demo Model"}],
        },
    )
    assert response.status_code == 200

    set_runtime_provider_api_key("custom", None)

    providers = client.get("/api/model-providers").json()["providers"]
    custom = next(provider for provider in providers if provider["provider_id"] == "custom")
    assert custom["api_key_configured"] is True
    assert "restart-safe-key" not in (tmp_path / "provider_settings.json").read_text(encoding="utf-8")
    assert "restart-safe-key" not in (tmp_path / "provider_secrets.json").read_text(encoding="utf-8")


def test_provider_model_fetch_error_redacts_query_api_key(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_dir", tmp_path)
    secret = "AIzaSyDANGER123456789"
    request = httpx.Request("GET", f"https://generativelanguage.googleapis.com/v1beta/models?key={secret}")
    response = httpx.Response(403, request=request)
    error = httpx.HTTPStatusError(
        f"Client error '403 Forbidden' for url '{request.url}'",
        request=request,
        response=response,
    )

    def fail_fetch(entry, stored):
        raise error

    monkeypatch.setattr(model_providers, "_fetch_models", fail_fetch)

    result = model_providers.fetch_provider_models("google")

    serialized = json.dumps(result, ensure_ascii=False)
    assert result["ok"] is False
    assert secret not in serialized
    assert "key=***" in result["last_error"]
    assert secret not in (tmp_path / "provider_settings.json").read_text(encoding="utf-8")


def test_processing_diagnostics_do_not_store_tracebacks_or_paths(tmp_path):
    db = SessionLocal()
    case_id = "CASE-SECURITY-TRACE"
    try:
        db.query(FieldResultRecord).filter(FieldResultRecord.case_id == case_id).delete()
        db.query(CaseRecord).filter(CaseRecord.case_id == case_id).delete()
        db.commit()
        case = CaseRecord(
            case_id=case_id,
            filename="missing.png",
            file_hash="missing",
            file_path=str(tmp_path / "missing.png"),
            status="queued",
        )
        db.add(case)
        db.commit()
        db.refresh(case)

        with pytest.raises(FileNotFoundError):
            process_case(db, case)

        db.refresh(case)
        diagnostics = json_loads(case.diagnostics_json, {})
    finally:
        db.query(FieldResultRecord).filter(FieldResultRecord.case_id == case_id).delete()
        db.query(CaseRecord).filter(CaseRecord.case_id == case_id).delete()
        db.commit()
        db.close()

    assert diagnostics["error_code"] == "PROCESSING_FAILED"
    assert "traceback" not in diagnostics
    assert str(tmp_path) not in json.dumps(diagnostics, ensure_ascii=False)


def test_review_writes_immutable_audit_record():
    db = SessionLocal()
    case_id = "CASE-SECURITY-AUDIT"
    try:
        db.query(FieldResultRecord).filter(FieldResultRecord.case_id == case_id).delete()
        db.query(CaseRecord).filter(CaseRecord.case_id == case_id).delete()
        if hasattr(database, "ReviewAuditRecord"):
            db.query(database.ReviewAuditRecord).filter(database.ReviewAuditRecord.case_id == case_id).delete()
        db.commit()
        db.add(
            CaseRecord(
                case_id=case_id,
                filename="case.txt",
                file_hash="hash",
                file_path="case.txt",
                status="completed",
                document_ir_json=DocumentIR(
                    document_id=case_id,
                    profile_id="medical_inpatient_zh",
                    source_filename="case.txt",
                    blocks=[
                        DocumentIRBlock(
                            block_id="b1",
                            page=1,
                            reading_order=1,
                            text="既往史：否认高血压。",
                            section_label="既往史",
                            confidence=0.98,
                        )
                    ],
                ).model_dump_json(),
            )
        )
        db.add(
            FieldResultRecord(
                case_id=case_id,
                field_key="hypertension_history",
                payload_json=ValidatedFieldResult(
                    field_key="hypertension_history",
                    field_group_key="history",
                    normalized_code="unknown",
                    status="unknown",
                    review_required=True,
                ).model_dump_json(),
            )
        )
        db.commit()
        client = TestClient(app)

        response = client.post(
            f"/api/cases/{case_id}/review",
            json={
                "field_key": "hypertension_history",
                "normalized_code": "0",
                "raw_value": "无",
                "reviewer": "reviewer-a",
                "comment": "confirmed from chart",
                "evidence_span": "否认高血压",
                "evidence_block_id": "b1",
            },
        )

        assert response.status_code == 200
        assert hasattr(database, "ReviewAuditRecord")
        audits = db.execute(
            select(database.ReviewAuditRecord).where(database.ReviewAuditRecord.case_id == case_id)
        ).scalars().all()
    finally:
        if hasattr(database, "ReviewAuditRecord"):
            db.query(database.ReviewAuditRecord).filter(database.ReviewAuditRecord.case_id == case_id).delete()
        db.query(FieldResultRecord).filter(FieldResultRecord.case_id == case_id).delete()
        db.query(CaseRecord).filter(CaseRecord.case_id == case_id).delete()
        db.commit()
        db.close()

    assert len(audits) == 1
    audit = audits[0]
    assert audit.field_key == "hypertension_history"
    assert audit.reviewer == "reviewer-a"
    assert json.loads(audit.before_json)["normalized_code"] == "unknown"
    assert json.loads(audit.after_json)["normalized_code"] == "0"


def test_start_script_binds_frontend_to_loopback_only():
    script = Path("scripts/start.ps1").read_text(encoding="utf-8")

    assert "--host 0.0.0.0" not in script
    assert "--host 127.0.0.1" in script


def test_stop_script_only_stops_eyex_processes():
    script = Path("scripts/stop.ps1").read_text(encoding="utf-8")

    assert "Get-CimInstance" in script
    assert "CommandLine" in script
    assert "Stop-Process -Id $connection.OwningProcess -Force" not in script
