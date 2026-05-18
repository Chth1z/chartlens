from __future__ import annotations

import re


def _extract_unavailable_ocr_engines(diagnostics_payload: dict) -> list[str]:
    error = str(diagnostics_payload.get("error", ""))
    match = re.search(r"unavailable=([^;]+)", error)
    if not match:
        return []
    value = match.group(1).strip()
    return [] if value == "none" else [item.strip() for item in value.split(",") if item.strip()]


def _extract_attempted_ocr_engines(diagnostics_payload: dict) -> list[str]:
    error = str(diagnostics_payload.get("error", ""))
    match = re.search(r"attempted=([^;]+)", error)
    if not match:
        return []
    value = match.group(1).strip()
    return [] if value == "none" else [item.strip() for item in value.split(",") if item.strip()]


def _extract_unavailable_ocr_reasons(diagnostics_payload: dict) -> dict:
    error = str(diagnostics_payload.get("error", ""))
    match = re.search(r"reasons=([^;]+)", error)
    if not match:
        return {engine: _default_ocr_unavailable_reason(engine) for engine in _extract_unavailable_ocr_engines(diagnostics_payload)}
    value = match.group(1).strip()
    if value == "none":
        return {}
    reasons: dict[str, str] = {}
    for item in value.split("|"):
        name, separator, reason = item.strip().partition("=")
        if separator and name.strip() and reason.strip():
            reasons[name.strip()] = reason.strip()
    return reasons


def _default_ocr_unavailable_reason(engine: str) -> str:
    if engine == "document_ai_http":
        return "EYEX_OCR_DOCUMENT_AI_URL is not configured"
    if engine == "openai_document_vision":
        return "EYEX_OPENAI_API_KEY or OPENAI_API_KEY is not configured"
    if engine in {"paddleocr_vl", "paddle_structure_v3"}:
        return "Python package 'paddleocr' is not installed in the backend runtime"
    if engine == "docling":
        return "Python package 'docling' is not installed in the backend runtime"
    return "engine is unavailable"


def _extract_ocr_engine_errors(diagnostics_payload: dict) -> dict:
    error = diagnostics_payload.get("error")
    if not error:
        return {}
    match = re.search(r"errors=([^;]+)", str(error))
    if not match:
        return {"pipeline": error}
    value = match.group(1).strip()
    if value == "none":
        return {"pipeline": error}
    errors: dict[str, str] = {}
    for item in value.split("|"):
        name, separator, reason = item.strip().partition("=")
        if separator and name.strip() and reason.strip():
            errors[name.strip()] = reason.strip()
    return errors or {"pipeline": error}
