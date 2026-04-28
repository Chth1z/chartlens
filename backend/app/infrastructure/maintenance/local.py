from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.infrastructure.db.maintenance import clear_case_record_tables


class LocalMaintenance:
    def __init__(self, db: Session):
        self.db = db

    def clear_processing_cache(self) -> int:
        cache_dir = Path(settings.storage_dir) / "cache"
        if not cache_dir.exists():
            return 0
        file_count = sum(1 for path in cache_dir.rglob("*") if path.is_file())
        shutil.rmtree(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        return file_count

    def clear_all_cases(self) -> int:
        return clear_case_record_tables(self.db)
