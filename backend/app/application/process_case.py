from __future__ import annotations

from app.application.ports import CaseProcessor


class ProcessCaseUseCase:
    def __init__(self, processor: CaseProcessor):
        self._processor = processor

    def execute(self, case_id: str) -> None:
        self._processor.process_case(case_id)
