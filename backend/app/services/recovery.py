"""Startup recovery for in-flight processing runs abandoned by a process crash.

Called once at app startup after init_db(). Scans for processing_runs
with status 'started' (the only in-flight status used by ProcessingTrace)
and marks them failed with reason 'process_restart_aborted'. Their
associated cases are set to 'failed' so the operator sees the issue in
the case queue and can manually reprocess.

This routine is idempotent: running it twice is a no-op because the
first run transitions all 'started' runs to 'failed'.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.database import CaseRecord, ProcessingRunRecord, SessionLocal, json_dumps, json_loads

logger = logging.getLogger(__name__)

IN_FLIGHT_RUN_STATUSES = {"started"}
IN_FLIGHT_CASE_STATUSES = {"ocr", "extracting"}


def recover_abandoned_runs() -> int:
    """Mark abandoned processing runs as failed and rebound their cases.

    Returns the number of runs recovered.
    """
    db = SessionLocal()
    try:
        return _recover(db)
    finally:
        db.close()


def _recover(db: Session) -> int:
    abandoned_runs = (
        db.query(ProcessingRunRecord)
        .filter(ProcessingRunRecord.status.in_(IN_FLIGHT_RUN_STATUSES))
        .all()
    )
    if not abandoned_runs:
        return 0

    recovered_count = 0
    now = datetime.now(timezone.utc)

    for run in abandoned_runs:
        run.status = "failed"
        run.error_code = "PROCESS_RESTART_ABORTED"
        run.error_message = "Processing was interrupted by a process restart. Reprocess the case to retry."
        run.completed_at = now
        db.add(run)

        # Rebound the associated case to 'failed' if it's still in an in-flight status
        case = db.query(CaseRecord).filter(CaseRecord.case_id == run.case_id).first()
        if case and case.status in IN_FLIGHT_CASE_STATUSES:
            case.status = "failed"
            case.updated_at = now
            # Update diagnostics to surface the abort reason
            diag = json_loads(case.diagnostics_json, {})
            diag["error_code"] = "PROCESS_RESTART_ABORTED"
            diag["error"] = "处理被进程重启中断。请重新处理该病例。"
            case.diagnostics_json = json_dumps(diag)
            db.add(case)
            recovered_count += 1
            logger.warning(
                "Recovered abandoned case %s (run %s): status -> failed",
                case.case_id, run.run_id,
            )

    db.commit()
    if recovered_count:
        logger.info("Startup recovery: marked %d abandoned run(s) as failed", recovered_count)
    return recovered_count
