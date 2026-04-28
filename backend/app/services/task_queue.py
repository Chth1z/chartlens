from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import CaseRecord
from app.services.pipeline import process_case

_EXECUTOR = ThreadPoolExecutor(max_workers=settings.case_workers, thread_name_prefix="eyes-case")
_LOCK = threading.Lock()
_FUTURES: dict[str, Future] = {}


def submit_case_processing(case_id: str) -> None:
    with _LOCK:
        existing = _FUTURES.get(case_id)
        if existing and not existing.done():
            return
        _FUTURES[case_id] = _EXECUTOR.submit(_process_case_by_id, case_id)


def task_running(case_id: str) -> bool:
    with _LOCK:
        future = _FUTURES.get(case_id)
    return bool(future and not future.done())


def _process_case_by_id(case_id: str) -> None:
    db = SessionLocal()
    try:
        case = db.scalar(select(CaseRecord).where(CaseRecord.case_id == case_id))
        if case is None:
            return
        path = Path(case.file_path)
        if not path.exists():
            case.status = "failed"
            case.error_message = "Original case file is missing"
            db.commit()
            return
        process_case(db=db, case=case, payload=path.read_bytes())
    finally:
        db.close()
