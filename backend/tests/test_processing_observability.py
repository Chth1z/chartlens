from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.database import (
    CaseRecord,
    FieldResultRecord,
    ModelCallRecord,
    ProcessingEventRecord,
    ProcessingRunRecord,
    ReviewAuditRecord,
    SessionLocal,
    init_db,
    json_dumps,
    json_loads,
)
from app.core.settings import settings
from app.services.diagnostics import build_case_diagnostics, quality_summary
from app.services.pipeline import process_case
from app.services.llm_provider.local_extraction import ConservativeLocalProvider
from app.services.secret_store import unprotect_text


init_db()


def test_process_case_writes_traceable_runs_events_and_model_calls(tmp_path: Path):
    db = SessionLocal()
    case_id = "CASE-OBSERVABILITY-OK"
    try:
        _cleanup_case(db, case_id)
        case = _add_text_case(
            db,
            tmp_path,
            case_id,
            "基本信息：患者，男，66岁。\n\n既往史：否认高血压、糖尿病。\n个人史：无烟酒不良嗜好。",
        )

        process_case(db, case, semantic_provider=ConservativeLocalProvider())
        process_case(db, case, semantic_provider=ConservativeLocalProvider())
        db.refresh(case)

        runs = db.execute(
            select(ProcessingRunRecord)
            .where(ProcessingRunRecord.case_id == case_id)
            .order_by(ProcessingRunRecord.started_at)
        ).scalars().all()
        assert len(runs) == 2
        assert {run.status for run in runs} == {"completed"}
        assert all(run.duration_ms is not None and run.duration_ms >= 0 for run in runs)
        assert all(run.ocr_block_count > 0 for run in runs)
        assert all(run.result_count > 0 for run in runs)
        assert all(json.loads(run.config_snapshot_json)["storage_dir"] == str(settings.storage_dir) for run in runs)

        events = db.execute(
            select(ProcessingEventRecord)
            .where(ProcessingEventRecord.case_id == case_id)
            .order_by(ProcessingEventRecord.started_at)
        ).scalars().all()
        event_names = {event.step_name for event in events}
        assert {
            "load_upload",
            "ocr_document_ir",
            "normalize_document_layout",
            "deidentify_document_ir",
            "extract_document",
            "persist_results",
        }.issubset(event_names)
        assert all(event.run_id in {run.run_id for run in runs} for event in events)
        assert all(event.duration_ms is not None and event.duration_ms >= 0 for event in events)

        model_calls = db.execute(
            select(ModelCallRecord)
            .where(ModelCallRecord.case_id == case_id)
            .order_by(ModelCallRecord.created_at)
        ).scalars().all()
        assert len(model_calls) >= 2
        assert {call.run_id for call in model_calls}.issubset({run.run_id for run in runs})
        assert all(call.provider == "conservative-local-provider" for call in model_calls)
        assert any("hypertension_history" in json.loads(call.field_keys_json) for call in model_calls)
        assert all(call.duration_ms is not None and call.duration_ms >= 0 for call in model_calls)

        diagnostics = build_case_diagnostics(case)
        assert diagnostics["run_count"] == 2
        assert diagnostics["latest_run"]["run_id"] == runs[-1].run_id
        assert {call["run_id"] for call in diagnostics["model_calls"]}.issubset({run.run_id for run in runs})
        assert diagnostics["latest_run"]["step_timings"]["ocr_ms"] >= 0
        assert diagnostics["latest_run"]["step_timings"]["layout_ms"] >= 0
        assert diagnostics["latest_run"]["step_timings"]["extract_ms"] >= 0
        assert diagnostics["latest_run"]["step_timings"]["persist_ms"] >= 0
        assert "ocr_engine_errors" in diagnostics["latest_run"]["step_timings"]
    finally:
        _cleanup_case(db, case_id)
        db.close()


def test_process_case_uses_normalized_document_ir_while_preserving_raw_ocr(tmp_path: Path):
    db = SessionLocal()
    case_id = "CASE-LAYOUT-NORMALIZED"
    try:
        _cleanup_case(db, case_id)
        case = _add_text_case(
            db,
            tmp_path,
            case_id,
            "03-05入院记录（儿）（经治审签）  保存(S) 签名(F6) 打印(P)\n"
            "基本信息：患者，男，16岁。\n\n主诉：头晕9小时。",
        )

        process_case(db, case, semantic_provider=ConservativeLocalProvider())
        db.refresh(case)

        document_ir = json.loads(case.document_ir_json)
        block_texts = [block["text"] for block in document_ir["blocks"]]
        assert not any("保存(S)" in text for text in block_texts)
        assert document_ir["metadata"]["layout_normalization"]["removed_screen_chrome_blocks"] == 1

        if case.raw_document_ir_json:
            raw_protected = json_loads(case.raw_document_ir_json, {})
            raw_payload = unprotect_text(raw_protected) if raw_protected else None
            if raw_payload:
                assert "保存(S)" in raw_payload
    finally:
        _cleanup_case(db, case_id)
        db.close()


def test_failed_process_case_writes_safe_failed_run(tmp_path: Path):
    db = SessionLocal()
    case_id = "CASE-OBSERVABILITY-FAILED"
    try:
        _cleanup_case(db, case_id)
        missing_path = tmp_path / "missing.txt"
        case = CaseRecord(
            case_id=case_id,
            filename="missing.txt",
            file_hash="missing",
            file_path=str(missing_path),
            status="queued",
        )
        db.add(case)
        db.commit()
        db.refresh(case)

        with pytest.raises(FileNotFoundError):
            process_case(db, case, semantic_provider=ConservativeLocalProvider())

        run = db.execute(
            select(ProcessingRunRecord).where(ProcessingRunRecord.case_id == case_id)
        ).scalar_one()
        assert run.status == "failed"
        assert run.error_code == "PROCESSING_FAILED"
        assert "Traceback" not in (run.error_message or "")
        assert str(tmp_path) not in (run.error_message or "")

        failed_events = db.execute(
            select(ProcessingEventRecord).where(
                ProcessingEventRecord.case_id == case_id,
                ProcessingEventRecord.status == "failed",
            )
        ).scalars().all()
        assert failed_events

        db.refresh(case)
        diagnostics = json_loads(case.diagnostics_json, {})
        assert diagnostics["run_id"] == run.run_id
        assert "traceback" not in json.dumps(diagnostics, ensure_ascii=False).lower()
        assert str(tmp_path) not in json.dumps(diagnostics, ensure_ascii=False)
    finally:
        _cleanup_case(db, case_id)
        db.close()


def test_quality_summary_parses_failed_ocr_engine_timeout():
    case = CaseRecord(
        case_id="CASE-OCR-TIMEOUT",
        filename="timeout.pdf",
        file_hash="timeout",
        file_path="timeout.pdf",
        status="failed",
        diagnostics_json=json_dumps(
            {
                "error": (
                    "OCR_ENGINE_UNAVAILABLE: intelligent OCR produced no usable result; "
                    "status=no_engine_result; attempted=paddleocr_hybrid; unavailable=none; reasons=none; "
                    "errors=paddleocr_hybrid=[PAGE_TIMEOUT] paddleocr_hybrid: engine exceeded timeout of 45s"
                )
            }
        ),
    )

    summary = quality_summary(case)

    assert summary["ocr_attempted_engines"] == ["paddleocr_hybrid"]
    assert summary["ocr_unavailable_engines"] == []
    assert summary["ocr_engine_errors"]["paddleocr_hybrid"].startswith("[PAGE_TIMEOUT]")


def _add_text_case(db, tmp_path: Path, case_id: str, text: str) -> CaseRecord:
    file_path = tmp_path / f"{case_id}.txt"
    file_path.write_text(text, encoding="utf-8")
    case = CaseRecord(
        case_id=case_id,
        filename=file_path.name,
        file_hash="hash",
        file_path=str(file_path),
        status="queued",
    )
    db.add(case)
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
