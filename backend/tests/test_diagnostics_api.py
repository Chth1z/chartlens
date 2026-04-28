from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_case_diagnostics_include_run_quality_and_fragments():
    created = client.post(
        "/api/cases",
        files={
            "file": (
                "diagnostics.txt",
                "基本信息：性别：女 年龄：66岁\n既往史：高血压病史10年。\n出院情况：好转出院。".encode("utf-8"),
                "text/plain",
            )
        },
    ).json()

    response = client.get(f"/api/cases/{created['case_id']}/diagnostics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["case_id"] == created["case_id"]
    assert payload["latest_run"]["status"] == "completed"
    assert payload["quality"]["ocr_block_count"] >= 3
    assert payload["quality"]["fragment_count"] >= 3
    assert any(fragment["section_name"] == "既往史" for fragment in payload["fragments"])
    assert payload["config"]["ocr_default_profile"] == "accurate"


def test_case_reprocess_creates_new_processing_run():
    created = client.post(
        "/api/cases",
        files={"file": ("reprocess.txt", "性别：男\n年龄：60岁".encode("utf-8"), "text/plain")},
    ).json()
    before = client.get(f"/api/cases/{created['case_id']}/diagnostics").json()

    response = client.post(f"/api/cases/{created['case_id']}/reprocess")

    assert response.status_code == 200
    after = client.get(f"/api/cases/{created['case_id']}/diagnostics").json()
    assert response.json()["status"] == "processed"
    assert after["run_count"] == before["run_count"] + 1


def test_vision_fallback_request_requires_manual_confirmation():
    created = client.post(
        "/api/cases",
        files={"file": ("vision.txt", "性别：男".encode("utf-8"), "text/plain")},
    ).json()

    rejected = client.post(
        f"/api/cases/{created['case_id']}/vision-fallback-requests",
        json={"page": 1, "reason": "低质量页", "reviewer": "tester", "manual_redaction_confirmed": False},
    )
    accepted = client.post(
        f"/api/cases/{created['case_id']}/vision-fallback-requests",
        json={"page": 1, "reason": "已人工确认裁剪图脱敏", "reviewer": "tester", "manual_redaction_confirmed": True},
    )

    assert rejected.status_code == 400
    assert accepted.status_code == 201
    assert accepted.json()["status"] == "approved_pending"
