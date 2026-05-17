from __future__ import annotations

import hashlib
import inspect
import json
import re
from pathlib import Path

from app.core.config_loader import load_document_profile, load_ocr_profile
from app.core.settings import settings
from app.domain.models import DocumentIR, DocumentIRBlock, DocumentIRSection, DocumentProfile
from app.services.domain_profile import document_kind_for_section
from app.services.ocr_engine import extract_with_intelligent_ocr


SECTION_SPLIT = re.compile(r"(?P<label>[\u4e00-\u9fffA-Za-z0-9 -]{2,18})\s*[:：]")
PDF_TEXT_MIN_CHARS = 20
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
OCR_DEBUG_METADATA_KEYS = (
    "ocr_candidate_metrics",
    "render_dpi_candidates",
    "render_dpi",
    "tile_max_side_len",
    "tile_overlap",
    "rapidocr_max_side_len",
    "image_preprocess",
    "image_preprocess_modes",
    "directml_safe_mode",
    "preprocess_profile",
    "merge_policy_version",
    "pipeline_stages",
    "stage_models",
    "stage_metrics",
)
OCR_DEBUG_LIST_METADATA_KEYS = {"ocr_candidate_metrics", "pipeline_stages", "stage_metrics"}


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


def _read_ocr_cache(payload: bytes, *, page: int, page_kind: str = "image_pdf_ocr") -> tuple[list[DocumentIRBlock], dict] | None:
    path = _ocr_cache_path(payload, page=page, engine_id=_route_cache_engine_id(page_kind), **_active_ocr_cache_dimensions())
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        blocks = [DocumentIRBlock.model_validate(item) for item in data.get("blocks", []) if isinstance(item, dict)]
        metadata = data.get("metadata", {})
    except Exception:
        return None
    if not blocks or not isinstance(metadata, dict):
        return None
    return blocks, metadata


def _write_ocr_cache(payload: bytes, blocks: list[DocumentIRBlock], metadata: dict, *, page: int, page_kind: str = "image_pdf_ocr") -> None:
    path = _ocr_cache_path(payload, page=page, engine_id=_route_cache_engine_id(page_kind), **_active_ocr_cache_dimensions())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"blocks": [block.model_dump() for block in blocks], "metadata": metadata},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _ocr_cache_path(
    payload: bytes,
    *,
    page: int,
    page_image_hash: str | None = None,
    ocr_profile_id: str | None = None,
    ocr_profile_version: str | None = None,
    engine_id: str | None = None,
    engine_version: str | None = None,
    model_name: str | None = None,
    model_version: str | None = None,
    accelerator: str | None = None,
    render_dpi: int | None = None,
    preprocess_profile: str | None = None,
    stage: str | None = None,
    merge_policy_version: str | None = None,
    ocr_options_fingerprint: str | None = None,
    layout_profile: str = "intelligent_document",
) -> Path:
    cache_key = hashlib.sha256(
        (
            f"{file_sha256(payload)}:{page}:{page_image_hash or file_sha256(payload)}:"
            f"{ocr_profile_id or settings.ocr_profile}:{ocr_profile_version or 'default'}:{engine_id or 'profile_route'}:"
            f"{engine_version or 'default'}:{model_name or 'default'}:{model_version or 'default'}:"
            f"{accelerator or settings.ocr_accelerator}:{render_dpi or 'default'}:"
            f"{preprocess_profile or 'default'}:{stage or 'default'}:{merge_policy_version or 'default'}:"
            f"{ocr_options_fingerprint or 'default'}:"
            f"{layout_profile}:{settings.ocr_route_version}:{settings.ocr_strategy}:"
            f"{_ocr_extractor_cache_fingerprint()}"
        ).encode("utf-8")
    ).hexdigest()
    return settings.storage_dir / "ocr_cache" / f"{cache_key}.json"


def _route_cache_engine_id(page_kind: str) -> str:
    try:
        from app.services.ocr_engine.engine_base import _engine_names_for_page_kind

        names = _engine_names_for_page_kind(page_kind)
    except Exception:
        names = []
    return f"route:{page_kind}:{','.join(names)}" if names else f"route:{page_kind}"


def _active_ocr_cache_dimensions() -> dict:
    try:
        profile = load_ocr_profile(settings.ocr_profile)
    except Exception:
        return {}
    return {
        "ocr_profile_version": profile.version,
        "render_dpi": profile.render_dpi,
        "preprocess_profile": profile.preprocess_profile,
        "merge_policy_version": profile.merge_policy_version,
        "ocr_options_fingerprint": _ocr_profile_options_fingerprint(profile),
    }


def _ocr_profile_options_fingerprint(profile) -> str:
    relevant = {
        "pipeline_stages": profile.pipeline_stages,
        "stage_models": profile.stage_models,
        "cache_policy": profile.cache_policy,
    }
    encoded = json.dumps(relevant, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _ocr_extractor_cache_fingerprint() -> str:
    from app.services.ocr_engine.canonicalize import CANONICAL_LAYOUT_VERSION

    module = getattr(extract_with_intelligent_ocr, "__module__", "unknown")
    qualname = getattr(extract_with_intelligent_ocr, "__qualname__", "unknown")
    return f"{module}.{qualname}:{CANONICAL_LAYOUT_VERSION}"


def _annotate_ocr_blocks(blocks: list[DocumentIRBlock], metadata: dict, source_page_kind: str) -> list[DocumentIRBlock]:
    engine = metadata.get("ocr_engine") or metadata.get("ocr_adapter") or "intelligent_document"
    model_name = metadata.get("model_name")
    model_version = metadata.get("model_version")
    accelerator = metadata.get("accelerator") or settings.ocr_accelerator
    engine_version = metadata.get("engine_version")
    route_profile_id = metadata.get("route_profile_id") or settings.ocr_profile
    annotated: list[DocumentIRBlock] = []
    for block in blocks:
        flags = list(block.quality_flags)
        if block.confidence < settings.ocr_intelligent_min_confidence and "low_confidence" not in flags:
            flags.append("low_confidence")
        annotated.append(
            block.model_copy(
                update={
                    "source_engine": str(engine),
                    "source_page_kind": source_page_kind,
                    "ocr_profile": settings.ocr_profile,
                    "layout_profile": "intelligent_document",
                    "quality_flags": flags,
                    "model_name": str(model_name) if model_name else block.model_name,
                    "model_version": str(model_version) if model_version else block.model_version,
                    "accelerator": str(accelerator) if accelerator else block.accelerator,
                    "engine_version": str(engine_version) if engine_version else block.engine_version,
                    "route_profile_id": str(route_profile_id) if route_profile_id else block.route_profile_id,
                }
            )
        )
    return annotated


def _extract_pdf_blocks(file_path: Path, payload: bytes, profile: DocumentProfile) -> tuple[list[DocumentIRBlock], dict]:
    text_pages = _extract_pdf_text_pages(file_path)
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


def _with_cache_status(metadata: dict, status: str) -> dict:
    updated = {**metadata, "ocr_cache_status": status}
    page_quality = []
    for item in metadata.get("ocr_page_quality", []):
        if isinstance(item, dict):
            page_quality.append({**item, "cache_status": status})
    if page_quality:
        updated["ocr_page_quality"] = page_quality
    return updated


def _page_quality_from_blocks(
    blocks: list[DocumentIRBlock],
    metadata: dict,
    *,
    default_page: int,
    cache_status: str,
) -> list[dict]:
    if not blocks:
        return [
            {
                "page": default_page,
                "kind": "image_pdf_ocr",
                "char_count": 0,
                "avg_confidence": 0.0,
                "quality_band": "poor",
                "cache_status": cache_status,
                "engine": metadata.get("ocr_engine", "none"),
                "failure_reason": metadata.get("ocr_intelligent_status", "no_engine_result"),
            }
        ]
    pages = sorted({block.page for block in blocks})
    quality = []
    for page in pages:
        page_blocks = [block for block in blocks if block.page == page]
        char_count = sum(len(block.text.strip()) for block in page_blocks)
        avg_confidence = sum(block.confidence for block in page_blocks) / len(page_blocks) if page_blocks else 0.0
        kind = page_blocks[0].source_page_kind or "image_pdf_ocr"
        quality.append(
            {
                "page": page,
                "kind": kind,
                "char_count": char_count,
                "avg_confidence": round(avg_confidence, 4),
                "quality_band": _quality_band(avg_confidence),
                "cache_status": cache_status,
                "engine": metadata.get("ocr_engine", "intelligent_document"),
            }
        )
    return quality


def _text_page_quality(page: int, text: str, kind: str) -> dict:
    confidence = 0.98 if text.strip() else 0.0
    return {
        "page": page,
        "kind": kind,
        "char_count": len(text.strip()),
        "avg_confidence": confidence,
        "quality_band": _quality_band(confidence),
        "cache_status": "not_applicable",
        "engine": "pdf_text" if kind == "native_pdf_text" else kind,
    }


def _quality_band(confidence: float) -> str:
    if confidence >= 0.9:
        return "good"
    if confidence >= 0.75:
        return "fair"
    return "poor"


def _combined_cache_status(metadata_items) -> str:
    statuses = [item.get("ocr_cache_status") for item in metadata_items if isinstance(item, dict)]
    if statuses and all(status == "hit" for status in statuses):
        return "hit"
    if statuses and any(status == "hit" for status in statuses):
        return "partial"
    if statuses and all(status == "miss" for status in statuses):
        return "miss"
    return "not_applicable"


def _merge_ocr_debug_metadata(metadata_items) -> dict:
    merged: dict = {}
    seen_by_key: dict[str, set[str]] = {}
    for metadata in metadata_items:
        if not isinstance(metadata, dict):
            continue
        for key in OCR_DEBUG_METADATA_KEYS:
            value = metadata.get(key)
            if value in (None, "", [], {}):
                continue
            if key in OCR_DEBUG_LIST_METADATA_KEYS:
                values = value if isinstance(value, list) else [value]
                target = merged.setdefault(key, [])
                seen = seen_by_key.setdefault(key, set())
                for item in values:
                    signature = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
                    if signature in seen:
                        continue
                    seen.add(signature)
                    target.append(item)
                continue
            if key not in merged:
                merged[key] = value
    return merged


def _ocr_unavailable_message(metadata: dict) -> str:
    unavailable = ", ".join(metadata.get("ocr_unavailable_engines", [])) or "none"
    attempted = ", ".join(metadata.get("ocr_attempted_engines", [])) or "none"
    status = metadata.get("ocr_intelligent_status", "no_engine_result")
    reasons = metadata.get("ocr_unavailable_reasons", {})
    errors = metadata.get("ocr_engine_errors", {})
    reason_text = " | ".join(f"{name}={reason}" for name, reason in reasons.items()) or "none"
    error_text = " | ".join(f"{name}={str(error).replace(';', ',')}" for name, error in errors.items()) or "none"
    return (
        "OCR_ENGINE_UNAVAILABLE: intelligent OCR produced no usable result; "
        f"status={status}; attempted={attempted}; unavailable={unavailable}; reasons={reason_text}; errors={error_text}"
    )


def _call_intelligent_ocr(file_path: Path, profile: DocumentProfile, *, page_kind: str) -> tuple[list[DocumentIRBlock], dict]:
    parameters = inspect.signature(extract_with_intelligent_ocr).parameters
    if "document_profile" in parameters:
        return extract_with_intelligent_ocr(file_path, profile.section_aliases, page_kind=page_kind, document_profile=profile)
    if "page_kind" in parameters:
        return extract_with_intelligent_ocr(file_path, profile.section_aliases, page_kind=page_kind)
    return extract_with_intelligent_ocr(file_path, profile.section_aliases)


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


def _blocks_from_text_pages(
    pages: list[tuple[int, str]],
    profile: DocumentProfile,
    *,
    source_engine: str = "pdf_text",
    source_page_kind: str = "native_pdf_text",
) -> list[DocumentIRBlock]:
    blocks: list[DocumentIRBlock] = []
    current_section = "未知"
    reading_order = 0
    for page, text in pages:
        normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
        raw_parts = [part.strip() for part in re.split(r"\n{2,}", normalized_text) if part.strip()]
        if len(raw_parts) <= 1:
            raw_parts = [line.strip() for line in normalized_text.split("\n") if line.strip()]
        if not raw_parts and normalized_text.strip():
            raw_parts = [normalized_text.strip()]
        for raw in raw_parts:
            reading_order += 1
            section = _detect_section(raw, profile.section_aliases) or current_section
            current_section = section
            blocks.append(_make_text_block(raw, page, reading_order, section, source_engine, source_page_kind, profile))
    return blocks


def _make_text_block(
    text: str,
    page: int,
    reading_order: int,
    section: str,
    source_engine: str,
    source_page_kind: str,
    profile: DocumentProfile,
) -> DocumentIRBlock:
    block_id = f"b{reading_order:04d}-{hashlib.sha1(f'{page}:paragraph:{text}'.encode('utf-8')).hexdigest()[:8]}"
    return DocumentIRBlock(
        block_id=block_id,
        page=page,
        reading_order=reading_order,
        text=text,
        bbox=[],
        confidence=0.98 if text else 0.0,
        block_type="paragraph",
        section_id=_section_id(section),
        section_label=section,
        document_kind=document_kind_for_section(section, profile),
        source_engine=source_engine,
        source_page_kind=source_page_kind,
        ocr_profile=settings.ocr_profile,
        layout_profile="text_layout",
        quality_flags=[] if text else ["empty_text"],
        route_profile_id=settings.ocr_profile,
        accelerator="cpu",
        model_name="pdf_text" if source_engine == "pdf_text" else source_engine,
        engine_version=source_engine,
    )


def _renumber_blocks(blocks: list[DocumentIRBlock]) -> list[DocumentIRBlock]:
    ordered = sorted(blocks, key=lambda block: (block.page, block.reading_order, block.block_id))
    return [block.model_copy(update={"reading_order": index}) for index, block in enumerate(ordered, start=1)]


def _detect_section(text: str, aliases: dict[str, list[str]]) -> str | None:
    prefix = text[:40]
    for label, names in aliases.items():
        for alias in names:
            if prefix.startswith(alias) or re.match(rf"^\s*{re.escape(alias)}\s*[:：]", prefix):
                return label
    match = SECTION_SPLIT.match(prefix)
    if match:
        found = match.group("label").strip()
        for label, names in aliases.items():
            if found in names:
                return label
    return None


def _sections_from_blocks(blocks: list[DocumentIRBlock], aliases: dict[str, list[str]]) -> list[DocumentIRSection]:
    seen: dict[str, list[int]] = {}
    for block in blocks:
        seen.setdefault(block.section_label, []).append(block.page)
    return [
        DocumentIRSection(
            section_id=_section_id(label),
            label=label,
            aliases=aliases.get(label, []),
            page_range=sorted(set(pages)),
            confidence=0.9 if label != "未知" else 0.2,
        )
        for label, pages in seen.items()
    ]


def _section_id(label: str) -> str:
    return hashlib.sha1(label.encode("utf-8")).hexdigest()[:12]
