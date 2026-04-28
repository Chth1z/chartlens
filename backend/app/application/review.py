from __future__ import annotations

from app.application.ports import CaseRepository
from app.domain.clinical import ReviewUpdate


class ReviewField:
    def __init__(self, repository: CaseRepository):
        self.repository = repository

    def execute(self, case_id: str, update: ReviewUpdate) -> dict:
        return self.repository.review_field(case_id, update)
