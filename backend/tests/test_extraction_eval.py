"""Tests for the field extraction evaluation service and CLI.

Covers: report schema stability, missing-case handling, no-gold-cases
template path, single-case scoring, summary aggregation, and the CLI
exit-code contract.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import (
    CaseRecord,
    FieldResultRecord,
    ModelCallRecord,
    ProcessingEventRecord,
    ProcessingRunRecord,
    ReviewAuditRecord,
    SessionLocal,
    init_db,
)
from app.domain.models import EvaluationGoldCase, EvaluationProfile
from app.services.extraction_eval import (
    REPORT_SCHEMA_VERSION,
    evaluate_case_against_gold,
    run_extraction_evaluation,
    summarize_eval_cases,
)


init_db()


@pytest.fixture(autouse=True)
def _clean_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _add_case_with_results(db, case_id: str, *, results: list[dict], diagnostics: dict | None = None) -> CaseRecord:
    _cleanup_case(db, case_id)
    case = CaseRecord(
        case_id=case_id,
        filename=f"{case_id}.txt",
        file_hash="hash",
        file_path=f"/tmp/{case_id}.txt",
        status="completed",
        document_ir_json=json.dumps({"blocks": [], "metadata": {"ocr_engine": "test", "quality_band": "high"}}),
        diagnostics_json=json.dumps(diagnostics or {"llm_usage": []}),
    )
    db.add(case)
    db.flush()
    for payload in results:
        db.add(FieldResultRecord(case_id=case_id, field_key=payload["field_key"], payload_json=json.dumps(payload)))
    db.commit()
    db.refresh(case)
    return case


def _cleanup_case(db, case_id: str) -> None:
    db.query(ModelCallRecord).filter(ModelCallRecord.case_id == case_id).delete()
    db.query(ProcessingEventRecord).filter(ProcessingEventRecord.case_id == case_id).delete()
    db.query(ProcessingRunRecord).filter(ProcessingRunRecord.case_id == case_id).delete()
    db.query(ReviewAuditRecord).filter(ReviewAuditRecord.case_id == case_id).delete()
    db.query(FieldResultRecord).filter(FieldResultRecord.case_id == case_id).delete()
    db.query(CaseRecord).filter(CaseRecord.case_id == case_id).delete()
    db.commit()


def _make_field_result(field_key: str, normalized_code: str, *, auto_accepted: bool, has_evidence: bool) -> dict:
    payload = {
        "field_key": field_key,
        "field_group_key": "demographics_group",
        "raw_value": normalized_code if normalized_code != "unknown" else None,
        "normalized_code": normalized_code,
        "status": "confirmed" if normalized_code != "unknown" else "not_mentioned",
        "confidence": 0.9 if normalized_code != "unknown" else 0.0,
        "evidence_text": "patient header" if has_evidence else None,
        "evidence_span": "patient header" if has_evidence else None,
        "evidence_block_id": "block-001" if has_evidence else None,
        "evidence_type": "explicit_positive" if has_evidence else "no_evidence",
        "page": 1,
        "bbox": [0, 0, 100, 20],
        "facts": [],
        "reasoning_summary": "test",
        "review_required": not auto_accepted,
        "auto_accepted": auto_accepted,
        "validation_state": "accepted" if auto_accepted else "needs_review",
        "validator_messages": [],
        "provenance": {"source": "test"},
        "evidence_candidates": [],
        "evidence_packs": [],
    }
    return payload


def test_evaluate_case_against_gold_scores_correctly():
    case_id = "CASE-EXT-EVAL-OK"
    db = SessionLocal()
    try:
        _add_case_with_results(
            db,
            case_id,
            results=[
                _make_field_result("gender", "1", auto_accepted=True, has_evidence=True),
                _make_field_result("age", "66", auto_accepted=True, has_evidence=True),
                _make_field_result("hospital", "unknown", auto_accepted=False, has_evidence=False),
            ],
        )
        gold = {"gender": "1", "age": "66", "hospital": "unknown"}
        report = evaluate_case_against_gold(case_id, gold, db, tags=["smoke"])
        assert report["status"] == "evaluated"
        assert report["total_fields"] == 3
        assert report["correct"] == 3
        assert report["accuracy"] == 1.0
        assert report["auto_accept_count"] == 2
        assert report["auto_accept_correct"] == 2
        assert report["auto_accept_precision"] == 1.0
        assert report["unknown_misfills"] == 0
        assert report["expected_unknown"] == 1
        assert report["evidence_coverage"] == 1.0
        assert {field["field_key"] for field in report["fields"]} == {"gender", "age", "hospital"}
        assert report["tags"] == ["smoke"]
    finally:
        _cleanup_case(db, case_id)
        db.close()


def test_evaluate_case_against_gold_flags_missing_evidence_and_misfill():
    case_id = "CASE-EXT-EVAL-BAD"
    db = SessionLocal()
    try:
        _add_case_with_results(
            db,
            case_id,
            results=[
                # auto-accepted but wrong answer
                _make_field_result("gender", "2", auto_accepted=True, has_evidence=True),
                # predicted non-unknown for an expected-unknown field
                _make_field_result("age", "30", auto_accepted=True, has_evidence=True),
                # predicted non-unknown without evidence span
                _make_field_result("hospital", "X", auto_accepted=False, has_evidence=False),
            ],
        )
        gold = {"gender": "1", "age": "unknown", "hospital": "X"}
        report = evaluate_case_against_gold(case_id, gold, db)
        assert report["correct"] == 1  # only hospital matches
        assert report["unknown_misfills"] == 1  # age was 'unknown' but predicted '30'
        assert report["unknown_misfill_rate"] == 1.0
        # Two predictions had evidence (gender, age) but hospital prediction lacked it.
        assert report["evidence_coverage"] == pytest.approx(2 / 3)
        assert report["auto_accept_correct"] == 0
        assert report["auto_accept_precision"] == 0.0
    finally:
        _cleanup_case(db, case_id)
        db.close()


def test_evaluate_case_against_gold_returns_missing_case_payload_when_db_lacks_case():
    db = SessionLocal()
    try:
        _cleanup_case(db, "CASE-DOES-NOT-EXIST")
        report = evaluate_case_against_gold(
            "CASE-DOES-NOT-EXIST",
            {"gender": "1", "age": "unknown"},
            db,
        )
        assert report["status"] == "missing_case"
        assert report["correct"] == 0
        assert report["expected_unknown"] == 1
        assert report["fields"][0]["error_code"] == "CASE_NOT_PROCESSED"
        assert "CASE-DOES-NOT-EXIST" in report["blocker_message"]
    finally:
        db.close()


def test_summarize_eval_cases_aggregates_and_flags_blockers():
    cases = [
        {
            "case_id": "ok",
            "status": "evaluated",
            "total_fields": 2,
            "correct": 2,
            "auto_accept_count": 2,
            "auto_accept_correct": 2,
            "unknown_misfills": 0,
            "expected_unknown": 0,
            "predicted_non_unknown": 2,
            "evidence_covered": 2,
            "usage": {"input_tokens": 100, "output_tokens": 20, "cached_input_tokens": 0, "cost_usd": 0.0001},
            "tags": [],
            "ocr_quality": {"quality_band": "high"},
            "fields": [
                {"field_key": "gender", "expected": "1", "actual": "1", "correct": True, "auto_accepted": True, "has_evidence": True, "review_required": False, "error_code": None},
                {"field_key": "age", "expected": "66", "actual": "66", "correct": True, "auto_accepted": True, "has_evidence": True, "review_required": False, "error_code": None},
            ],
        },
        {
            "case_id": "missing",
            "status": "missing_case",
            "total_fields": 1,
            "correct": 0,
            "auto_accept_count": 0,
            "auto_accept_correct": 0,
            "unknown_misfills": 0,
            "expected_unknown": 0,
            "predicted_non_unknown": 0,
            "evidence_covered": 0,
            "usage": {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0, "cost_usd": 0.0},
            "tags": [],
            "ocr_quality": {"quality_band": "unknown"},
            "fields": [],
        },
    ]
    summary = summarize_eval_cases(cases, field_tags={"gender": ["demographics"]})
    assert summary["case_count"] == 2
    assert summary["evaluated_case_count"] == 1
    assert summary["blocked_case_count"] == 1
    assert summary["accuracy"] == 1.0
    assert summary["auto_accept_precision"] == 1.0
    assert summary["hard_blocker"] == "missing_processed_cases"
    assert summary["blocked_case_ids"] == ["missing"]
    assert summary["field_tags"]["demographics"]["accuracy"] == 1.0
    # OCR quality bands only reflect evaluated cases. Missing cases do not
    # contribute to quality distributions because they have no document.
    assert summary["ocr_quality_bands"] == {"high": 1}


def test_run_extraction_evaluation_returns_template_blocker_when_no_gold_cases():
    profile = EvaluationProfile(
        profile_id="empty_profile",
        label="empty",
        schema_id="medical_inpatient_zh",
        gold_cases=[],
        thresholds={"auto_accept_precision": 0.95},
        token_budget={"max_input_tokens_per_case": 1000},
    )
    db = SessionLocal()
    try:
        report = run_extraction_evaluation(profile, db=db)
        assert report["schema_version"] == REPORT_SCHEMA_VERSION
        assert report["summary"]["hard_blocker"] == "no_gold_cases"
        assert report["summary"]["thresholds"] == {"auto_accept_precision": 0.95}
        assert report["cases"] == []
    finally:
        db.close()


def test_run_extraction_evaluation_produces_full_report_for_gold_profile():
    case_id = "CASE-EXT-EVAL-PROFILE"
    db = SessionLocal()
    try:
        _add_case_with_results(
            db,
            case_id,
            results=[
                _make_field_result("gender", "1", auto_accepted=True, has_evidence=True),
                _make_field_result("age", "66", auto_accepted=True, has_evidence=True),
            ],
        )
        profile = EvaluationProfile(
            profile_id="smoke",
            label="smoke",
            schema_id="medical_inpatient_zh",
            gold_cases=[EvaluationGoldCase(case_id=case_id, gold={"gender": "1", "age": "66"}, tags=["demo"])],
            field_tags={"gender": ["demographics"], "age": ["demographics"]},
            thresholds={"auto_accept_precision": 0.95},
            token_budget={"max_input_tokens_per_case": 1000},
        )
        report = run_extraction_evaluation(profile, db=db)
        assert report["schema_version"] == REPORT_SCHEMA_VERSION
        assert report["profile"]["profile_id"] == "smoke"
        assert report["profile"]["gold_case_count"] == 1
        assert report["summary"]["accuracy"] == 1.0
        assert report["summary"]["auto_accept_precision"] == 1.0
        assert "hard_blocker" not in report["summary"]
        assert report["cases"][0]["case_id"] == case_id
        assert report["cases"][0]["tags"] == ["demo"]
    finally:
        _cleanup_case(db, case_id)
        db.close()


def _load_extraction_eval_cli_module():
    module_path = ROOT / "scripts" / "run-extraction-eval.py"
    spec = importlib.util.spec_from_file_location("run_extraction_eval_cli", module_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_extraction_eval_cli_exits_nonzero_for_blocked_profile(monkeypatch, capsys):
    module = _load_extraction_eval_cli_module()

    def fake_runner(profile_id: str, *, db) -> dict:
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "profile": {"profile_id": profile_id},
            "summary": {"hard_blocker": "no_gold_cases"},
            "cases": [],
        }

    monkeypatch.setattr(module, "run_extraction_evaluation_profile", fake_runner)
    monkeypatch.setattr(module.sys, "argv", ["run-extraction-eval.py", "--profile-id", "mock_general"])

    exit_code = module.main()
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "no_gold_cases" in captured.out


def test_extraction_eval_cli_allows_blocked_with_flag(monkeypatch, capsys):
    module = _load_extraction_eval_cli_module()

    def fake_runner(profile_id: str, *, db) -> dict:
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "profile": {"profile_id": profile_id},
            "summary": {"hard_blocker": "no_gold_cases"},
            "cases": [],
        }

    monkeypatch.setattr(module, "run_extraction_evaluation_profile", fake_runner)
    monkeypatch.setattr(module.sys, "argv", ["run-extraction-eval.py", "--profile-id", "mock_general", "--allow-blocked"])

    exit_code = module.main()
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "no_gold_cases" in captured.out


def test_extraction_eval_cli_returns_zero_for_clean_run(monkeypatch, capsys):
    module = _load_extraction_eval_cli_module()

    def fake_runner(profile_id: str, *, db) -> dict:
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "profile": {"profile_id": profile_id},
            "summary": {"accuracy": 1.0},
            "cases": [],
        }

    monkeypatch.setattr(module, "run_extraction_evaluation_profile", fake_runner)
    monkeypatch.setattr(module.sys, "argv", ["run-extraction-eval.py", "--profile-id", "mock_general"])

    exit_code = module.main()
    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["schema_version"] == REPORT_SCHEMA_VERSION
