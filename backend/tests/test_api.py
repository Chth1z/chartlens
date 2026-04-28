from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_endpoint_reports_service_status():
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_upload_case_creates_case_and_initial_results():
    response = client.post(
        "/api/cases",
        files={"file": ("case.txt", "姓名：张三\n性别：男\n年龄：62岁\n既往史：高血压病史10年。".encode("utf-8"), "text/plain")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["case_id"].startswith("CASE-")
    assert payload["status"] in {"processed", "queued"}
    assert any(result["field_key"] == "gender" for result in payload["results"])


def test_upload_case_can_enqueue_background_processing(monkeypatch):
    from app.core.config import settings
    from app.api import routes

    submitted: list[str] = []

    monkeypatch.setattr(settings, "sync_pipeline", False)
    monkeypatch.setattr(routes, "submit_case_processing", lambda case_id: submitted.append(case_id))

    response = client.post(
        "/api/cases",
        files={"file": ("queued.txt", "性别：男\n年龄：62岁".encode("utf-8"), "text/plain")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["results"] == []
    assert submitted == [payload["case_id"]]


def test_review_update_records_audit_entry():
    created = client.post(
        "/api/cases",
        files={"file": ("review.txt", "性别：女\n既往史：否认高血压病史。".encode("utf-8"), "text/plain")},
    ).json()
    case_id = created["case_id"]

    response = client.patch(
        f"/api/cases/{case_id}/review",
        json={
            "field_key": "hypertension_history",
            "new_raw_value": "无",
            "new_normalized_code": "0",
            "reason": "证据中明确否认",
            "reviewer": "tester",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["field_key"] == "hypertension_history"
    assert payload["normalized_code"] == "0"
    assert payload["review_required"] is False


def test_export_case_returns_xlsx():
    created = client.post(
        "/api/cases",
        files={"file": ("export.txt", "性别：男\n年龄：66岁\n出院情况：好转出院。".encode("utf-8"), "text/plain")},
    ).json()

    response = client.get(f"/api/cases/{created['case_id']}/export.xlsx")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument")
    assert response.content.startswith(b"PK")
