from fastapi.testclient import TestClient

from app.core.settings import settings
from app.main import app


def test_health_endpoint():
    client = TestClient(app)
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_upload_text_case_end_to_end(monkeypatch):
    monkeypatch.setattr(settings, "llm_mode", "disabled")
    client = TestClient(app)
    response = client.post(
        "/api/cases",
        files={"file": ("case.txt", "基本信息：患者，男，66岁。\n\n既往史：否认高血压。".encode("utf-8"), "text/plain")},
    )

    assert response.status_code == 200
    case_id = response.json()["case_id"]

    # The background worker may still be running; synchronous reprocess gives deterministic smoke coverage.
    rerun = client.post(f"/api/cases/{case_id}/reprocess")
    assert rerun.status_code == 200

    results = client.get(f"/api/cases/{case_id}/results")
    assert results.status_code == 200
    by_key = {item["field_key"]: item for item in results.json()}
    assert by_key["gender"]["normalized_code"] == "1"
    assert by_key["hypertension_history"]["normalized_code"] == "0"
