"""Tests for startup recovery of abandoned processing runs (E0-003)."""
import pytest
from datetime import datetime, timezone

from app.core.database import (
    CaseRecord, ProcessingRunRecord, SessionLocal, init_db, json_dumps, json_loads
)
from app.services.recovery import recover_abandoned_runs, _recover


@pytest.fixture(autouse=True)
def _setup_db():
    """Ensure clean tables for each test."""
    init_db()
    db = SessionLocal()
    try:
        db.query(ProcessingRunRecord).delete()
        db.query(CaseRecord).delete()
        db.commit()
    finally:
        db.close()


def _make_case(db, case_id: str, status: str) -> CaseRecord:
    case = CaseRecord(
        case_id=case_id,
        filename="test.txt",
        file_hash="abc123",
        file_path="/tmp/test.txt",
        status=status,
        diagnostics_json=json_dumps({"steps": []}),
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def _make_run(db, case_id: str, run_id: str, status: str) -> ProcessingRunRecord:
    run = ProcessingRunRecord(
        run_id=run_id,
        case_id=case_id,
        status=status,
        config_snapshot_json=json_dumps({}),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def test_recovery_marks_started_runs_as_failed():
    db = SessionLocal()
    try:
        _make_case(db, "CASE-001", "extracting")
        _make_run(db, "CASE-001", "run-001", "started")

        count = _recover(db)

        assert count == 1
        run = db.query(ProcessingRunRecord).filter_by(run_id="run-001").first()
        assert run.status == "failed"
        assert run.error_code == "PROCESS_RESTART_ABORTED"
        assert run.completed_at is not None

        case = db.query(CaseRecord).filter_by(case_id="CASE-001").first()
        assert case.status == "failed"
        diag = json_loads(case.diagnostics_json, {})
        assert diag["error_code"] == "PROCESS_RESTART_ABORTED"
    finally:
        db.close()


def test_recovery_is_idempotent():
    db = SessionLocal()
    try:
        _make_case(db, "CASE-002", "ocr")
        _make_run(db, "CASE-002", "run-002", "started")

        count1 = _recover(db)
        assert count1 == 1

        count2 = _recover(db)
        assert count2 == 0  # Already recovered
    finally:
        db.close()


def test_recovery_ignores_completed_runs():
    db = SessionLocal()
    try:
        _make_case(db, "CASE-003", "completed")
        _make_run(db, "CASE-003", "run-003", "completed")

        count = _recover(db)

        assert count == 0
        case = db.query(CaseRecord).filter_by(case_id="CASE-003").first()
        assert case.status == "completed"  # Unchanged
    finally:
        db.close()


def test_recovery_ignores_already_failed_runs():
    db = SessionLocal()
    try:
        _make_case(db, "CASE-004", "failed")
        _make_run(db, "CASE-004", "run-004", "failed")

        count = _recover(db)

        assert count == 0
    finally:
        db.close()


def test_recovery_does_not_rebound_completed_case():
    """If the run is 'started' but the case already completed (race condition),
    don't rebound the case to failed."""
    db = SessionLocal()
    try:
        _make_case(db, "CASE-005", "completed")
        _make_run(db, "CASE-005", "run-005", "started")

        count = _recover(db)

        # Run is marked failed but case stays completed
        assert count == 0  # Case was not in in-flight status
        run = db.query(ProcessingRunRecord).filter_by(run_id="run-005").first()
        assert run.status == "failed"
        case = db.query(CaseRecord).filter_by(case_id="CASE-005").first()
        assert case.status == "completed"
    finally:
        db.close()
