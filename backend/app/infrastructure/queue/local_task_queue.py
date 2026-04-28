from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor

from app.application.process_case import ProcessCaseUseCase
from app.core.config import settings
from app.infrastructure.pipeline.case_processor import SqlAlchemyCaseProcessor

_EXECUTOR = ThreadPoolExecutor(max_workers=settings.case_workers, thread_name_prefix="chartlens-case")
_LOCK = threading.Lock()
_FUTURES: dict[str, Future] = {}


class LocalTaskQueue:
    def submit_case_processing(self, case_id: str) -> None:
        submit_case_processing(case_id)

    def process_case_now(self, case_id: str) -> None:
        process_case_now(case_id)


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


def process_case_now(case_id: str) -> None:
    _process_case_by_id(case_id)


def _process_case_by_id(case_id: str) -> None:
    ProcessCaseUseCase(SqlAlchemyCaseProcessor()).execute(case_id)
