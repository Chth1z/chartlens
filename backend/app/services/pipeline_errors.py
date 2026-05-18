from __future__ import annotations

from app.core.database import json_dumps
from app.domain.models import DocumentIR
from app.services.secret_store import protect_text


def _public_error_message(exc: Exception) -> str:
    text = str(exc)
    if text.startswith("OCR_ENGINE_UNAVAILABLE:"):
        return text[:2000]
    return f"{type(exc).__name__}: processing failed; see backend logs for details"


def _protect_document_ir(document_ir: DocumentIR) -> str | None:
    protected = protect_text(document_ir.model_dump_json())
    return json_dumps(protected) if protected else None
