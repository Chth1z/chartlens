from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

from app.core.config_loader import load_document_profile
from app.core.settings import settings
from app.domain.models import DocumentIR, DocumentIRBlock, DocumentProfile
from app.services.ocr_engine import extract_with_intelligent_ocr

from app.services.ocr.blocks import (
    _blocks_from_text_pages,
    _renumber_blocks,
    _sections_from_blocks,
)
from app.services.ocr.cache import (
    _read_ocr_cache,
    _with_cache_status,
    _write_ocr_cache,
    _combined_cache_status,
)
from app.services.ocr.quality import (
    _annotate_ocr_blocks,
    _merge_ocr_debug_metadata,
    _ocr_unavailable_message,
    _page_quality_from_blocks,
    _text_page_quality,
)


PDF_TEXT_MIN_CHARS = 20
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def file_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def build_document_ir(file_path: Path, payload: bytes, *, document_id: str, profile_id: str | None = None) -> DocumentIR:
    profile = load_document_profile(profile_id)
    blocks, ocr_metadata = _extract_blocks(file_path, payload, profile)
    sections = _sections_from_blocks(blocks, profile.section_aliases)
    return DocumentIR(
        document_id=document_id,
        profile_id=profile.profile_id,
        source_filename=file_path.name,
        blocks=blocks,
        sections=sections,
        metadata={
            "ocr_profile": settings.ocr_profile,
            "ocr_adapter": "intelligent_document",
            "file_sha256": file_sha256(payload),
            **ocr_metadata,
        },
    )


def _extract_blocks(file_path: Path, payload: bytes, profile: DocumentProfile) -> tuple[list[DocumentIRBlock], dict]:
    suffix = file_path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return _blocks_from_text_pages(
            [(1, payload.decode("utf-8", errors="ignore"))],
            profile,
            source_engine="plain_text",
            source_page_kind="text",
        ), {
            "input_kind": "text",
            "ocr_page_quality": [_text_page_quality(1, payload.decode("utf-8", errors="ignore"), "plain_text")],
        }
    if suffix == ".pdf":
        return _extract_pdf_blocks(file_path, payload, profile)
    if suffix in IMAGE_SUFFIXES:
        cached = _read_ocr_cache(payload, page=1, page_kind="image_ocr")
        if cached:
            blocks, metadata = cached
            metadata = _with_cache_status(metadata, "hit")
            return blocks, {"input_kind": "image", **metadata, "ocr_cache_status": "hit"}
        blocks, metadata = _call_intelligent_ocr(file_path, profile, page_kind="image_ocr")
        if not blocks:
            raise RuntimeError(_ocr_unavailable_message(metadata))
        blocks = _annotate_ocr_blocks(blocks, metadata, "image_ocr")
        cache_metadata = {
            **metadata,
            "ocr_cache_status": "miss",
            "ocr_page_quality": _page_quality_from_blocks(blocks, metadata, default_page=1, cache_status="miss"),
        }
        _write_ocr_cache(payload, blocks, cache_metadata, page=1, page_kind="image_ocr")
        return blocks, {"input_kind": "image", **cache_metadata}
    return _blocks_from_text_pages(
        [(1, payload.decode("utf-8", errors="ignore"))],
        profile,
        source_engine="unknown_text",
        source_page_kind="unknown_text",
    ), {
        "input_kind": "unknown_text",
        "ocr_page_quality": [_text_page_quality(1, payload.decode("utf-8", errors="ignore"), "unknown_text")],
    }


def _extract_pdf_blocks(file_path: Path, payload: bytes, profile: DocumentProfile) -> tuple[list[DocumentIRBlock], dict]:
    # Look up _extract_pdf_text_pages via the package so tests that monkey-patch
    # `app.services.ocr._extract_pdf_text_pages` still affect this code path.
    from app.services import ocr as _pkg

    text_pages = _pkg._extract_pdf_text_pages(file_path)
    text_char_count = sum(len(text.strip()) for _, text in text_pages)
    native_pages = [(page, text) for page, text in text_pages if len(text.strip()) >= PDF_TEXT_MIN_CHARS]
    low_text_pages = [page for page, text in text_pages if len(text.strip()) < PDF_TEXT_MIN_CHARS] or ([1] if not text_pages else [])
    native_blocks = _blocks_from_text_pages(
        native_pages,
        profile,
        source_engine="pdf_text",
        source_page_kind="native_pdf_text",
    )
    if native_blocks and not low_text_pages:
        return native_blocks, {
            "input_kind": "native_pdf",
            "pdf_text_char_count": text_char_count,
            "pdf_page_count": len(text_pages),
            "pdf_native_text_pages": [page for page, _ in native_pages],
            "pdf_ocr_pages": [],
            "ocr_page_quality": [
                _text_page_quality(page, text, "native_pdf_text")
                for page, text in native_pages
            ],
        }

    blocks, metadata = _extract_pdf_ocr_pages(file_path, payload, profile, low_text_pages)
    if not blocks and not native_blocks:
        raise RuntimeError(_ocr_unavailable_message(metadata))
    if not blocks:
        metadata = {**metadata, "ocr_intelligent_status": "partial_native_text_only"}
    merged_blocks = _renumber_blocks([*native_blocks, *blocks])
    page_quality = [
        _text_page_quality(page, text, "native_pdf_text")
        for page, text in native_pages
    ]
    page_quality.extend(metadata.get("ocr_page_quality", []))
    return merged_blocks, {
        "input_kind": "mixed_pdf" if native_blocks and blocks else "image_pdf" if blocks else "native_pdf_partial",
        "pdf_text_char_count": text_char_count,
        "pdf_page_count": len(text_pages),
        "pdf_native_text_pages": [page for page, _ in native_pages],
        "pdf_ocr_pages": sorted({block.page for block in blocks}),
        "pdf_low_text_pages": low_text_pages,
        **metadata,
        "ocr_page_quality": sorted(page_quality, key=lambda item: item.get("page", 0)),
    }


def _extract_pdf_ocr_pages(
    file_path: Path,
    payload: bytes,
    profile: DocumentProfile,
    low_text_pages: list[int],
) -> tuple[list[DocumentIRBlock], dict]:
    if not low_text_pages:
        return [], {"ocr_page_quality": []}
    blocks_by_page: dict[int, list[DocumentIRBlock]] = {}
    metadata_by_page: dict[int, dict] = {}
    shared_blocks: list[DocumentIRBlock] | None = None
    shared_metadata: dict | None = None
    for page in low_text_pages:
        cached = _read_ocr_cache(payload, page=page, page_kind="image_pdf_ocr")
        if cached:
            blocks, metadata = cached
            blocks_by_page[page] = blocks
            metadata_by_page[page] = _with_cache_status(metadata, "hit")
            continue
        if shared_blocks is None:
            raw_blocks, raw_metadata = _call_intelligent_ocr(file_path, profile, page_kind="image_pdf_ocr")
            shared_metadata = raw_metadata
            shared_blocks = _annotate_ocr_blocks(raw_blocks, raw_metadata, "image_pdf_ocr") if raw_blocks else []
        page_blocks = [block for block in shared_blocks if block.page == page]
        if not page_blocks and len(low_text_pages) == 1:
            page_blocks = shared_blocks
        page_metadata = {
            **(shared_metadata or {}),
            "ocr_cache_status": "miss",
            "ocr_page_quality": _page_quality_from_blocks(
                page_blocks,
                shared_metadata or {},
                default_page=page,
                cache_status="miss",
            ),
        }
        if page_blocks:
            _write_ocr_cache(payload, page_blocks, page_metadata, page=page, page_kind="image_pdf_ocr")
        blocks_by_page[page] = page_blocks
        metadata_by_page[page] = page_metadata

    blocks = [block for page in low_text_pages for block in blocks_by_page.get(page, [])]
    attempted = []
    unavailable = []
    errors: dict = {}
    reasons: dict = {}
    page_quality = []
    engine = "none"
    status = "no_engine_result"
    for metadata in metadata_by_page.values():
        attempted.extend(metadata.get("ocr_attempted_engines", []))
        unavailable.extend(metadata.get("ocr_unavailable_engines", []))
        errors.update(metadata.get("ocr_engine_errors", {}))
        reasons.update(metadata.get("ocr_unavailable_reasons", {}))
        page_quality.extend(metadata.get("ocr_page_quality", []))
        engine = metadata.get("ocr_engine") or engine
        status = metadata.get("ocr_intelligent_status") or status
    return blocks, {
        "ocr_adapter": "intelligent_document",
        "ocr_engine": engine,
        "ocr_intelligent_status": status if blocks else "no_engine_result",
        "ocr_attempted_engines": list(dict.fromkeys(attempted)),
        "ocr_unavailable_engines": list(dict.fromkeys(unavailable)),
        "ocr_unavailable_reasons": reasons,
        "ocr_engine_errors": errors,
        "ocr_page_quality": page_quality,
        "ocr_cache_status": _combined_cache_status(metadata_by_page.values()),
        **_merge_ocr_debug_metadata(metadata_by_page.values()),
    }


def _call_intelligent_ocr(file_path: Path, profile: DocumentProfile, *, page_kind: str) -> tuple[list[DocumentIRBlock], dict]:
    # Look up `extract_with_intelligent_ocr` via the package so tests that
    # monkey-patch `app.services.ocr.extract_with_intelligent_ocr` still work.
    from app.services import ocr as _pkg

    func = _pkg.extract_with_intelligent_ocr
    parameters = inspect.signature(func).parameters
    if "document_profile" in parameters:
        return func(file_path, profile.section_aliases, page_kind=page_kind, document_profile=profile)
    if "page_kind" in parameters:
        return func(file_path, profile.section_aliases, page_kind=page_kind)
    return func(file_path, profile.section_aliases)


def _extract_pdf_text_pages(file_path: Path) -> list[tuple[int, str]]:
    try:
        from pypdf import PdfReader
    except Exception:
        return []
    reader = PdfReader(str(file_path))
    pages: list[tuple[int, str]] = []
    for index, page in enumerate(reader.pages, start=1):
        pages.append((index, page.extract_text() or ""))
    return pages
