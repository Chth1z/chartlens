from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile, status

from app.application.cases import CreateCase, DeleteCase, GetCase, ListCases, ReprocessCase
from app.application.field_dictionary import GetFieldDictionary
from app.application.ports import CaseRepository, FieldDictionaryProvider, FileStore, RuntimeSettings, TaskQueue
from app.composition.dependencies import (
    get_case_repository,
    get_dictionary_provider,
    get_file_store,
    get_runtime_settings,
    get_task_queue,
)
from app.domain.auth import AuthUser
from app.interfaces.http.auth_service import require_user

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/field-dictionary")
def field_dictionary(provider: FieldDictionaryProvider = Depends(get_dictionary_provider)) -> dict:
    return GetFieldDictionary(provider).execute()


@router.get("/cases")
def list_cases(
    _: AuthUser = Depends(require_user),
    repository: CaseRepository = Depends(get_case_repository),
) -> list[dict]:
    return ListCases(repository).execute()


@router.post("/cases", status_code=status.HTTP_201_CREATED)
async def create_case(
    file: UploadFile = File(...),
    _: AuthUser = Depends(require_user),
    repository: CaseRepository = Depends(get_case_repository),
    file_store: FileStore = Depends(get_file_store),
    task_queue: TaskQueue = Depends(get_task_queue),
    runtime: RuntimeSettings = Depends(get_runtime_settings),
) -> dict:
    return CreateCase(
        repository=repository,
        file_store=file_store,
        task_queue=task_queue,
        runtime=runtime,
    ).execute(filename=file.filename or "case.bin", payload=await file.read())


@router.get("/cases/{case_id}")
def get_case(
    case_id: str,
    _: AuthUser = Depends(require_user),
    repository: CaseRepository = Depends(get_case_repository),
) -> dict:
    return GetCase(repository).execute(case_id)


@router.delete("/cases/{case_id}")
def delete_case(
    case_id: str,
    _: AuthUser = Depends(require_user),
    repository: CaseRepository = Depends(get_case_repository),
) -> dict:
    return DeleteCase(repository).execute(case_id)


@router.post("/cases/{case_id}/reprocess")
def reprocess_case(
    case_id: str,
    _: AuthUser = Depends(require_user),
    repository: CaseRepository = Depends(get_case_repository),
    task_queue: TaskQueue = Depends(get_task_queue),
    runtime: RuntimeSettings = Depends(get_runtime_settings),
) -> dict:
    return ReprocessCase(repository=repository, task_queue=task_queue, runtime=runtime).execute(case_id)
