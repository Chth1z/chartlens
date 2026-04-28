from __future__ import annotations

from app.application.ports import CaseRepository
from app.domain.clinical import EvalRunRequest


class RunEval:
    def __init__(self, repository: CaseRepository):
        self.repository = repository

    def execute(self, request: EvalRunRequest) -> dict:
        return self.repository.create_eval_run(request)
