from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


client = TestClient(app)


def test_delete_case_removes_related_records():
    created = client.post(
        "/api/cases",
        files={"file": ("delete-me.txt", "性别：男\n年龄：70岁".encode("utf-8"), "text/plain")},
    ).json()

    deleted = client.delete(f"/api/cases/{created['case_id']}")
    fetched = client.get(f"/api/cases/{created['case_id']}")
    diagnostics = client.get(f"/api/cases/{created['case_id']}/diagnostics")

    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True
    assert deleted.json()["affected_count"] == 1
    assert fetched.status_code == 404
    assert diagnostics.status_code == 404


def test_clear_cache_only_removes_cache_files(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_dir", tmp_path, raising=False)
    cache_dir = tmp_path / "cache"
    uploads_dir = tmp_path / "uploads"
    cache_dir.mkdir(parents=True)
    uploads_dir.mkdir(parents=True)
    (cache_dir / "cached.json").write_text("{}", encoding="utf-8")
    (uploads_dir / "upload.txt").write_text("keep", encoding="utf-8")

    response = client.post("/api/maintenance/clear-cache")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["affected_count"] == 1
    assert not (cache_dir / "cached.json").exists()
    assert (uploads_dir / "upload.txt").exists()


def test_clear_all_cases_removes_cases_but_keeps_model_token(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "chatgpt_token_cache_path", tmp_path / "auth" / "chatgpt_tokens.json", raising=False)
    token_path = Path(settings.chatgpt_token_cache_path)
    token_path.parent.mkdir(parents=True)
    token_path.write_text("{}", encoding="utf-8")
    client.post(
        "/api/cases",
        files={"file": ("clear-all.txt", "性别：女".encode("utf-8"), "text/plain")},
    )

    response = client.post("/api/maintenance/clear-all-cases")
    cases = client.get("/api/cases")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["affected_count"] >= 1
    assert cases.json() == []
    assert token_path.exists()
