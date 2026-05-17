from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app.core.database import CaseRecord
from app.core.settings import settings


SOURCE_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
PDF_SOURCE_PREVIEW_MIN_SCALE = 0.5
PDF_SOURCE_PREVIEW_MAX_SCALE = 8.5


@dataclass(frozen=True)
class SourcePageFile:
    path: Path
    media_type: str
    cache_status: str
    dpi: int | None = None
    width: int | None = None
    height: int | None = None


class SourcePageError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def resolve_case_source_page(case: CaseRecord, page: int) -> SourcePageFile:
    if page < 1:
        raise SourcePageError(404, "PDF page not found")
    render_dpi = case_page_render_dpi(case, page) or positive_float(case_document_metadata(case).get("render_dpi"))
    cached = _cached_source_page(case, page, render_dpi)
    if cached is not None:
        return cached

    source_path = _case_source_path(case)
    suffix = source_path.suffix.lower()
    if suffix in SOURCE_IMAGE_SUFFIXES:
        if page != 1:
            raise SourcePageError(404, "Source image has only one page")
        return SourcePageFile(path=source_path, media_type=source_image_media_type(suffix), cache_status="source", dpi=_rounded_dpi(render_dpi))
    if suffix == ".pdf":
        return _materialize_pdf_source_page(case, source_path, page, render_dpi)
    raise SourcePageError(415, "Original preview is only available for image or PDF uploads")


def pdf_source_render_scale(case: CaseRecord, page: int) -> float:
    metadata = case_document_metadata(case)
    scale = positive_float(metadata.get("pdf_render_scale"))
    if scale is not None:
        return _clamp_pdf_scale(scale)
    render_dpi = case_page_render_dpi(case, page) or positive_float(metadata.get("render_dpi"))
    if render_dpi is not None:
        return _clamp_pdf_scale(render_dpi / 72.0)
    return 3.0


def case_document_payload(case: CaseRecord) -> dict:
    if not case.document_ir_json:
        return {}
    try:
        import json

        payload = json.loads(case.document_ir_json)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def case_document_metadata(case: CaseRecord) -> dict:
    payload = case_document_payload(case)
    metadata = payload.get("metadata") if isinstance(payload, dict) else None
    return metadata if isinstance(metadata, dict) else {}


def case_page_render_dpi(case: CaseRecord, page: int) -> float | None:
    blocks = case_document_payload(case).get("blocks")
    if not isinstance(blocks, list):
        return None
    page_dpis: list[float] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        try:
            block_page = int(block.get("page") or 1)
        except Exception:
            block_page = 1
        if block_page != page:
            continue
        render_dpi = positive_float(block.get("render_dpi"))
        if render_dpi is not None:
            page_dpis.append(render_dpi)
    return max(page_dpis) if page_dpis else None


def positive_float(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return float(value)
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def source_image_media_type(suffix: str) -> str:
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    if suffix in {".tif", ".tiff"}:
        return "image/tiff"
    if suffix == ".bmp":
        return "image/bmp"
    return "application/octet-stream"


def _materialize_pdf_source_page(case: CaseRecord, source_path: Path, page: int, render_dpi: float | None) -> SourcePageFile:
    try:
        import pypdfium2
    except Exception as exc:
        raise SourcePageError(415, "PDF page preview requires pypdfium2") from exc

    scale = pdf_source_render_scale(case, page)
    dpi = _rounded_dpi(render_dpi or scale * 72.0)
    target = _source_page_cache_path(case, page, dpi)
    if target.exists():
        return SourcePageFile(path=target, media_type="image/png", cache_status="hit", dpi=dpi)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    try:
        with pypdfium2.PdfDocument(str(source_path)) as pdf:
            if page > len(pdf):
                raise SourcePageError(404, "PDF page not found")
            bitmap = pdf[page - 1].render(scale=scale)
            image = bitmap.to_pil()
            image.save(tmp, format="PNG")
            tmp.replace(target)
            return SourcePageFile(
                path=target,
                media_type="image/png",
                cache_status="miss",
                dpi=dpi,
                width=image.width,
                height=image.height,
            )
    except SourcePageError:
        raise
    except Exception as exc:
        raise SourcePageError(500, "Failed to render PDF source page") from exc
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _case_source_path(case: CaseRecord) -> Path:
    try:
        source_path = Path(case.file_path).resolve(strict=True)
        storage_root = settings.storage_dir.resolve()
    except FileNotFoundError:
        raise SourcePageError(404, "Original case file not found and no materialized page image is available") from None
    except Exception as exc:
        raise SourcePageError(400, "Invalid original case file path") from exc
    if source_path != storage_root and storage_root not in source_path.parents:
        raise SourcePageError(403, "Original case file is outside configured storage")
    return source_path


def _cached_source_page(case: CaseRecord, page: int, render_dpi: float | None) -> SourcePageFile | None:
    dpi = _rounded_dpi(render_dpi) if render_dpi is not None else None
    if dpi is not None:
        path = _source_page_cache_path(case, page, dpi)
        if path.exists():
            return SourcePageFile(path=path, media_type="image/png", cache_status="hit", dpi=dpi)
    candidates = sorted(_source_page_cache_dir(case).glob(f"page-{page:04d}-dpi-*.png"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not candidates:
        return None
    cached_dpi = _dpi_from_cache_name(candidates[0].name)
    return SourcePageFile(path=candidates[0], media_type="image/png", cache_status="hit", dpi=cached_dpi)


def _source_page_cache_path(case: CaseRecord, page: int, dpi: int | None) -> Path:
    file_hash = "".join(ch for ch in (case.file_hash or "unknown") if ch.isalnum())[:24] or "unknown"
    dpi_label = str(dpi) if dpi is not None else "unknown"
    return _source_page_cache_dir(case) / f"page-{page:04d}-dpi-{dpi_label}-{file_hash}.png"


def _source_page_cache_dir(case: CaseRecord) -> Path:
    safe_case_id = "".join(ch for ch in case.case_id if ch.isalnum() or ch in {"-", "_"}) or "case"
    return settings.storage_dir / "source_pages" / safe_case_id


def _rounded_dpi(value: float | None) -> int | None:
    if value is None:
        return None
    return max(1, int(round(value)))


def _dpi_from_cache_name(name: str) -> int | None:
    parts = name.split("-")
    try:
        dpi_index = parts.index("dpi")
        return int(parts[dpi_index + 1])
    except Exception:
        return None


def _clamp_pdf_scale(scale: float) -> float:
    return max(PDF_SOURCE_PREVIEW_MIN_SCALE, min(PDF_SOURCE_PREVIEW_MAX_SCALE, scale))
