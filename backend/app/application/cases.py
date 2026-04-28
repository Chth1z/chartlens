from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.application.errors import NotFoundError
from app.application.ports import CaseRepository, FileStore, RuntimeSettings, TaskQueue


class ListCases:
    def __init__(self, repository: CaseRepository):
        self.repository = repository

    def execute(self) -> list[dict]:
        return self.repository.list_cases()


class GetCase:
    def __init__(self, repository: CaseRepository):
        self.repository = repository

    def execute(self, case_id: str) -> dict:
        return self.repository.get_case(case_id)


class CreateCase:
    def __init__(
        self,
        *,
        repository: CaseRepository,
        file_store: FileStore,
        task_queue: TaskQueue,
        runtime: RuntimeSettings,
    ):
        self.repository = repository
        self.file_store = file_store
        self.task_queue = task_queue
        self.runtime = runtime

    def execute(self, *, filename: str, payload: bytes) -> dict:
        file_hash, path = self.file_store.save_upload_bytes(filename=filename, payload=payload)
        suffix = "-DUP" if self.repository.case_exists_by_hash(file_hash) else ""
        case_id = f"CASE-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:8].upper()}{suffix}"
        record = self.repository.create_case(
            case_id=case_id,
            filename=filename or path.name,
            file_hash=file_hash,
            file_path=str(path),
        )
        if self.runtime.sync_pipeline:
            self.task_queue.process_case_now(case_id)
            return self.repository.get_case(case_id)
        self.task_queue.submit_case_processing(case_id)
        return record


class ReprocessCase:
    def __init__(self, *, repository: CaseRepository, task_queue: TaskQueue, runtime: RuntimeSettings):
        self.repository = repository
        self.task_queue = task_queue
        self.runtime = runtime

    def execute(self, case_id: str) -> dict:
        path = self.repository.get_case_file_path(case_id)
        if not path.exists():
            raise NotFoundError("Original case file is missing")
        self.repository.set_case_queued(case_id)
        if self.runtime.sync_pipeline:
            self.task_queue.process_case_now(case_id)
            return self.repository.get_case(case_id)
        self.task_queue.submit_case_processing(case_id)
        return self.repository.get_case(case_id)


class DeleteCase:
    def __init__(self, repository: CaseRepository):
        self.repository = repository

    def execute(self, case_id: str) -> dict:
        affected = self.repository.delete_case(case_id)
        return {"ok": True, "affected_count": affected, "message": "Case deleted"}
