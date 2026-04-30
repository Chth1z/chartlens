from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path

from app.core.settings import settings

SCHEME_WIN32_DPAPI = "win32-dpapi"


def save_provider_api_key(provider_id: str, api_key: str | None) -> bool:
    provider_id = provider_id.strip()
    if not provider_id:
        return False
    payload = _load_store()
    if not api_key:
        payload.pop(provider_id, None)
        _write_store(payload)
        return True
    protected = _protect_secret(api_key)
    if not protected:
        return False
    payload[provider_id] = protected
    _write_store(payload)
    return True


def load_provider_api_key(provider_id: str | None) -> str | None:
    if not provider_id:
        return None
    item = _load_store().get(provider_id)
    if not isinstance(item, dict):
        return None
    return _unprotect_secret(item)


def protect_text(secret: str) -> dict | None:
    return _protect_secret(secret)


def unprotect_text(item: dict) -> str | None:
    return _unprotect_secret(item)


def _store_path() -> Path:
    return settings.storage_dir / "provider_secrets.json"


def _load_store() -> dict:
    path = _store_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_store(payload: dict) -> None:
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    _store_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _protect_secret(secret: str) -> dict | None:
    if os.name != "nt":
        return None
    blob = _win32_crypt_protect(secret.encode("utf-8"))
    return {"scheme": SCHEME_WIN32_DPAPI, "value": base64.b64encode(blob).decode("ascii")}


def _unprotect_secret(item: dict) -> str | None:
    if item.get("scheme") != SCHEME_WIN32_DPAPI or os.name != "nt":
        return None
    try:
        protected = base64.b64decode(str(item.get("value") or ""))
        return _win32_crypt_unprotect(protected).decode("utf-8")
    except Exception:
        return None


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.c_void_p)]


def _blob_from_bytes(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.c_void_p))
    return blob, buffer


def _win32_crypt_protect(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    input_blob, _input_buffer = _blob_from_bytes(data)
    output_blob = _DataBlob()
    ok = crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        "EYEX provider API key",
        None,
        None,
        None,
        0,
        ctypes.byref(output_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def _win32_crypt_unprotect(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    input_blob, _input_buffer = _blob_from_bytes(data)
    output_blob = _DataBlob()
    description = ctypes.c_void_p()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        ctypes.byref(description),
        None,
        None,
        None,
        0,
        ctypes.byref(output_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)
        if description.value:
            kernel32.LocalFree(description)
