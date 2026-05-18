from __future__ import annotations

from app.services.ocr_engine import extract_with_intelligent_ocr

from app.services.ocr.builder import (
    build_document_ir,
    file_sha256,
    _extract_blocks,
    _extract_pdf_blocks,
    _extract_pdf_ocr_pages,
    _extract_pdf_text_pages,
    _call_intelligent_ocr,
)
from app.services.ocr.cache import _ocr_cache_path, _ocr_extractor_cache_fingerprint

__all__ = ["build_document_ir", "file_sha256"]
