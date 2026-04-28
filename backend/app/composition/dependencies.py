from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.infrastructure.config.providers import EnvRuntimeSettings, YamlFieldDictionaryProvider, YamlSystemConfigProvider
from app.infrastructure.config.settings_status_provider import YamlSettingsStatusProvider
from app.infrastructure.db.repositories import SqliteCaseRepository
from app.infrastructure.db.session import get_db
from app.infrastructure.export.excel import ExcelExporter
from app.infrastructure.maintenance.local import LocalMaintenance
from app.infrastructure.queue.local_task_queue import LocalTaskQueue
from app.infrastructure.storage.files import LocalFileStore


def get_case_repository(db: Session = Depends(get_db)) -> SqliteCaseRepository:
    return SqliteCaseRepository(db)


def get_file_store() -> LocalFileStore:
    return LocalFileStore()


def get_task_queue() -> LocalTaskQueue:
    return LocalTaskQueue()


def get_runtime_settings() -> EnvRuntimeSettings:
    return EnvRuntimeSettings()


def get_dictionary_provider() -> YamlFieldDictionaryProvider:
    return YamlFieldDictionaryProvider()


def get_system_config_provider() -> YamlSystemConfigProvider:
    return YamlSystemConfigProvider()


def get_exporter() -> ExcelExporter:
    return ExcelExporter()


def get_settings_status_provider() -> YamlSettingsStatusProvider:
    return YamlSettingsStatusProvider()


def get_maintenance(db: Session = Depends(get_db)) -> LocalMaintenance:
    return LocalMaintenance(db)


def ensure_runtime_dirs() -> None:
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
