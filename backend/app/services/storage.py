from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings


def ensure_storage_dirs() -> None:
    for name in ("uploads", "exports"):
        (settings.storage_dir / name).mkdir(parents=True, exist_ok=True)


async def save_upload(upload: UploadFile) -> tuple[str, Path, bytes]:
    ensure_storage_dirs()
    payload = await upload.read()
    file_hash = hashlib.sha256(payload).hexdigest()
    suffix = Path(upload.filename or "case.bin").suffix or ".bin"
    target = settings.storage_dir / "uploads" / f"{file_hash}{suffix}"
    target.write_bytes(payload)
    return file_hash, target, payload
