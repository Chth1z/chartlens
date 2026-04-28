from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


client = TestClient(app)


def test_eval_run_returns_per_field_review_and_mismatch_metrics(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    created = client.post(
        "/api/cases",
        files={
            "file": (
                "eval-metrics.txt",
                "性别：男\n年龄：62岁\n既往史：高血压病史10年。".encode("utf-8"),
                "text/plain",
            )
        },
    ).json()

    response = client.post(
        "/api/evals/runs",
        json={
            "name": "metrics",
            "cases": [
                {
                    "case_id": created["case_id"],
                    "expected_fields": {
                        "gender": "2",
                        "age": "62",
                        "hypertension_history": "1",
                    },
                }
            ],
        },
    )

    assert response.status_code == 201
    metrics = response.json()["metrics"]
    assert metrics["per_field_metrics"]["gender"]["exact_matches"] == 0
    assert metrics["per_field_metrics"]["age"]["accuracy"] == 1.0
    assert metrics["review_required_rate"] == 0.0
    assert metrics["auto_accept_accuracy"] == 0.6667
    assert metrics["mismatches"][0]["field_key"] == "gender"
    assert metrics["mismatches"][0]["expected"] == "2"
    assert metrics["mismatches"][0]["actual"] == "1"
