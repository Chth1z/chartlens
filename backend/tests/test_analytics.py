"""Tests for the cost analytics endpoint."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.core.database import (
    CaseRecord,
    ModelCallRecord,
    ProcessingRunRecord,
    SessionLocal,
    init_db,
)
from app.main import app

init_db()

client = TestClient(app)

CASE_ID = "CASE-ANALYTICS-TEST"
RUN_ID = f"run-analytics-{uuid.uuid4().hex[:8]}"


def _cleanup(db) -> None:
    db.query(ModelCallRecord).filter(ModelCallRecord.case_id == CASE_ID).delete()
    db.query(ProcessingRunRecord).filter(ProcessingRunRecord.case_id == CASE_ID).delete()
    db.query(CaseRecord).filter(CaseRecord.case_id == CASE_ID).delete()
    db.commit()


def _seed_data(db) -> None:
    """Insert a case, run, and several model_call records for testing."""
    db.add(
        CaseRecord(
            case_id=CASE_ID,
            filename="analytics.txt",
            file_hash="analytics-hash",
            file_path="analytics.txt",
            status="completed",
        )
    )
    db.add(
        ProcessingRunRecord(
            run_id=RUN_ID,
            case_id=CASE_ID,
            status="completed",
        )
    )
    db.flush()

    now = datetime.now(timezone.utc)
    calls = [
        ModelCallRecord(
            call_id=f"call-analytics-{i}",
            run_id=RUN_ID,
            case_id=CASE_ID,
            stage="evidence_collection" if i < 2 else "extraction",
            provider="deepseek" if i % 2 == 0 else "anthropic",
            model="deepseek-v4" if i % 2 == 0 else "claude-sonnet",
            mode="structured",
            input_tokens=1000 * (i + 1),
            cached_input_tokens=200 * (i + 1),
            output_tokens=500 * (i + 1),
            cost_usd=0.01 * (i + 1),
            duration_ms=100 * (i + 1),
            status="completed",
            created_at=now - timedelta(hours=i),
        )
        for i in range(4)
    ]
    db.add_all(calls)

    # Add an old record outside the default 30-day window
    db.add(
        ModelCallRecord(
            call_id="call-analytics-old",
            run_id=RUN_ID,
            case_id=CASE_ID,
            stage="evidence_collection",
            provider="deepseek",
            model="deepseek-v4",
            mode="structured",
            input_tokens=9999,
            cached_input_tokens=1111,
            output_tokens=8888,
            cost_usd=0.99,
            duration_ms=5000,
            status="completed",
            created_at=now - timedelta(days=60),
        )
    )
    db.commit()


def test_cost_analytics_returns_valid_response():
    """Endpoint returns a well-formed response with expected fields."""
    response = client.get("/api/analytics/cost", params={"days": 30})
    assert response.status_code == 200
    data = response.json()
    assert data["period_days"] == 30
    assert "since" in data
    assert isinstance(data["total_call_count"], int)
    assert isinstance(data["total_input_tokens"], int)
    assert isinstance(data["total_output_tokens"], int)
    assert isinstance(data["total_cached_tokens"], int)
    assert isinstance(data["total_cost_usd"], float)
    assert isinstance(data["breakdown"], list)
    assert data["group_by"] == "provider"
    assert data["total_call_count"] >= 0
    assert data["total_cost_usd"] >= 0.0


def test_cost_analytics_aggregates_correctly():
    """After seeding records, totals include our seeded data."""
    db = SessionLocal()
    try:
        _cleanup(db)
        _seed_data(db)

        response = client.get("/api/analytics/cost", params={"days": 30})
        assert response.status_code == 200
        data = response.json()

        # At minimum, our 4 recent calls are included
        assert data["total_call_count"] >= 4
        # input_tokens from our calls: 1000+2000+3000+4000 = 10000
        assert data["total_input_tokens"] >= 10000
        # output_tokens from our calls: 500+1000+1500+2000 = 5000
        assert data["total_output_tokens"] >= 5000
        # cached: 200+400+600+800 = 2000
        assert data["total_cached_tokens"] >= 2000
        # cost: 0.01+0.02+0.03+0.04 = 0.10
        assert data["total_cost_usd"] >= 0.10 - 1e-6
        assert data["avg_duration_ms"] is not None
        assert data["group_by"] == "provider"
        # At least deepseek and anthropic in breakdown
        keys = {item["group_key"] for item in data["breakdown"]}
        assert "deepseek" in keys
        assert "anthropic" in keys
    finally:
        _cleanup(db)
        db.close()


def test_cost_analytics_group_by_model():
    """group_by=model returns breakdown keyed by model name."""
    db = SessionLocal()
    try:
        _cleanup(db)
        _seed_data(db)

        response = client.get("/api/analytics/cost", params={"days": 30, "group_by": "model"})
        assert response.status_code == 200
        data = response.json()

        assert data["group_by"] == "model"
        keys = {item["group_key"] for item in data["breakdown"]}
        assert "deepseek-v4" in keys
        assert "claude-sonnet" in keys
    finally:
        _cleanup(db)
        db.close()


def test_cost_analytics_group_by_case():
    """group_by=case returns breakdown keyed by case_id."""
    db = SessionLocal()
    try:
        _cleanup(db)
        _seed_data(db)

        response = client.get("/api/analytics/cost", params={"days": 30, "group_by": "case"})
        assert response.status_code == 200
        data = response.json()

        assert data["group_by"] == "case"
        keys = {item["group_key"] for item in data["breakdown"]}
        assert CASE_ID in keys
    finally:
        _cleanup(db)
        db.close()


def test_cost_analytics_group_by_stage():
    """group_by=stage returns breakdown keyed by stage."""
    db = SessionLocal()
    try:
        _cleanup(db)
        _seed_data(db)

        response = client.get("/api/analytics/cost", params={"days": 30, "group_by": "stage"})
        assert response.status_code == 200
        data = response.json()

        assert data["group_by"] == "stage"
        keys = {item["group_key"] for item in data["breakdown"]}
        assert "evidence_collection" in keys
        assert "extraction" in keys
    finally:
        _cleanup(db)
        db.close()


def test_cost_analytics_days_filter():
    """days parameter correctly filters old records."""
    db = SessionLocal()
    try:
        _cleanup(db)
        _seed_data(db)

        # With days=365, the old record (60 days ago) should be included
        response_wide = client.get("/api/analytics/cost", params={"days": 365})
        assert response_wide.status_code == 200
        data_wide = response_wide.json()

        # With days=7, only the 4 recent calls from our seed (old one excluded)
        response_narrow = client.get("/api/analytics/cost", params={"days": 7})
        assert response_narrow.status_code == 200
        data_narrow = response_narrow.json()

        # The wide window should have more calls than the narrow one
        # (at least 1 more from our old record)
        assert data_wide["total_call_count"] >= data_narrow["total_call_count"] + 1
    finally:
        _cleanup(db)
        db.close()


def test_cost_analytics_invalid_days():
    """days=0 or days=999 returns 422."""
    response = client.get("/api/analytics/cost", params={"days": 0})
    assert response.status_code == 422

    response = client.get("/api/analytics/cost", params={"days": 999})
    assert response.status_code == 422


def test_cost_analytics_invalid_group_by():
    """Invalid group_by value returns 422."""
    response = client.get("/api/analytics/cost", params={"group_by": "invalid"})
    assert response.status_code == 422
