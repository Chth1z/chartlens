from __future__ import annotations

import hashlib
from pathlib import Path

from app.core.config import settings


def ensure_storage_dirs() -> None:
    for name in ("uploads", "exports"):
        (settings.storage_dir / name).mkdir(parents=True, exist_ok=True)


class LocalFileStore:
    def save_upload_bytes(self, *, filename: str, payload: bytes) -> tuple[str, Path]:
        return save_upload_bytes(filename=filename, payload=payload)


def save_upload_bytes(*, filename: str, payload: bytes) -> tuple[str, Path]:
    ensure_storage_dirs()
    file_hash = hashlib.sha256(payload).hexdigest()
    suffix = Path(filename or "case.bin").suffix or ".bin"
    target = settings.storage_dir / "uploads" / f"{file_hash}{suffix}"
    target.write_bytes(payload)
    return file_hash, target
