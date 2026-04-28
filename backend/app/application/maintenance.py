from __future__ import annotations

from app.application.ports import CaseRepository, MaintenancePort


class DeleteCaseRecords:
    def __init__(self, repository: CaseRepository):
        self.repository = repository

    def execute(self, case_id: str) -> int:
        return self.repository.delete_case(case_id)


class ClearAllCases:
    def __init__(self, maintenance: MaintenancePort):
        self.maintenance = maintenance

    def execute(self) -> int:
        return self.maintenance.clear_all_cases()


class ClearProcessingCache:
    def __init__(self, maintenance: MaintenancePort):
        self.maintenance = maintenance

    def execute(self) -> int:
        return self.maintenance.clear_processing_cache()
