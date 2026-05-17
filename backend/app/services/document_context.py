from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from app.core.settings import settings
from app.domain.models import DocumentContext, DocumentContextPage, DocumentIR, DocumentIRBlock, DocumentPageImage


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def build_document_context(
    document_ir: DocumentIR,
    *,
    source_file_path: Path | None = None,
    materialize_images: bool = False,
    page_image_dir: Path | None = None,
    allow_raw_images_online: bool = False,
) -> DocumentContext:
    page_images = _page_images_from_metadata(document_ir.metadata)
    if source_file_path and materialize_images:
        page_images = {
            **page_images,
            **materialize_page_images(
                source_file_path,
                document_id=document_ir.document_id,
                output_dir=page_image_dir,
                allow_online=allow_raw_images_online,
            ),
        }

    pages: list[DocumentContextPage] = []
    for page_number in _page_numbers(document_ir, page_images):
        blocks = sorted(
            [block for block in document_ir.blocks if block.page == page_number],
            key=lambda block: block.reading_order,
        )
        image = page_images.get(page_number)
        pages.append(
            DocumentContextPage(
                page=page_number,
                blocks=blocks,
                tables=_tables_for_page(blocks),
                image=image,
                width=image.width if image else None,
                height=image.height if image else None,
                dpi=image.dpi if image else _render_dpi_for_blocks(blocks),
                quality=_page_quality(document_ir, page_number),
            )
        )

    return DocumentContext(
        document_id=document_ir.document_id,
        profile_id=document_ir.profile_id,
        source_filename=document_ir.source_filename,
        pages=pages,
        metadata={
            "context_version": "document-context-v1",
            "input_kind": document_ir.metadata.get("input_kind"),
            "ocr_engine": document_ir.metadata.get("ocr_engine"),
            "ocr_profile": document_ir.metadata.get("ocr_profile"),
            "has_page_images": any(page.image is not None for page in pages),
            "page_images_online_allowed": any(page.image and page.image.online_allowed for page in pages),
            "deidentification": document_ir.metadata.get("deidentification", {}),
        },
    )


def document_context_payload(
    context: DocumentContext,
    *,
    include_images: bool = True,
    max_blocks_per_page: int | None = None,
) -> dict[str, Any]:
    return {
        "document_id": context.document_id,
        "profile_id": context.profile_id,
        "source_filename": context.source_filename,
        "context_version": context.metadata.get("context_version", "document-context-v1"),
        "pages": [
            {
                "page": page.page,
                "width": page.width,
                "height": page.height,
                "dpi": page.dpi,
                "quality": page.quality,
                "image": _image_payload(page.image) if include_images else None,
                "blocks": [_block_payload(block) for block in _page_blocks_for_payload(page.blocks, max_blocks_per_page)],
                "tables": page.tables,
            }
            for page in context.pages
        ],
        "metadata": context.metadata,
    }


def materialize_page_images(
    source_file_path: Path,
    *,
    document_id: str,
    output_dir: Path | None = None,
    allow_online: bool = False,
) -> dict[int, DocumentPageImage]:
    source = Path(source_file_path)
    if not source.exists():
        return {}
    output_root = output_dir or settings.storage_dir / "page_images" / document_id
    output_root.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        target = output_root / f"page-0001{suffix}"
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        return {
            1: DocumentPageImage(
                page=1,
                path=str(target),
                sha256=_file_sha256(target),
                online_allowed=allow_online,
                source="source_image",
            )
        }
    if suffix == ".pdf":
        return _render_pdf_pages(source, output_root, allow_online=allow_online)
    return {}


def _page_images_from_metadata(metadata: dict[str, Any]) -> dict[int, DocumentPageImage]:
    images: dict[int, DocumentPageImage] = {}
    raw_images = metadata.get("page_images", [])
    if not isinstance(raw_images, list):
        return images
    for item in raw_images:
        if not isinstance(item, dict):
            continue
        try:
            image = DocumentPageImage.model_validate(item)
        except Exception:
            continue
        images[image.page] = image
    return images


def _page_numbers(document_ir: DocumentIR, page_images: dict[int, DocumentPageImage]) -> list[int]:
    pages = {block.page for block in document_ir.blocks}
    pages.update(page_images)
    return sorted(pages or {1})


def _tables_for_page(blocks: list[DocumentIRBlock]) -> list[dict[str, Any]]:
    table_ids = sorted({block.table_id for block in blocks if block.table_id})
    tables: list[dict[str, Any]] = []
    for table_id in table_ids:
        cells = [
            {
                "block_id": block.block_id,
                "text": block.text,
                "row": block.row,
                "col": block.col,
                "bbox": block.bbox,
                "confidence": block.confidence,
                "source_engine": block.source_engine,
            }
            for block in blocks
            if block.table_id == table_id
        ]
        tables.append({"table_id": table_id, "cells": sorted(cells, key=lambda item: (item["row"] or 0, item["col"] or 0))})
    return tables


def _page_quality(document_ir: DocumentIR, page: int) -> dict[str, Any]:
    for item in document_ir.metadata.get("ocr_page_quality", []):
        if isinstance(item, dict) and item.get("page") == page:
            return item
    page_blocks = [block for block in document_ir.blocks if block.page == page]
    if not page_blocks:
        return {}
    return {
        "page": page,
        "block_count": len(page_blocks),
        "avg_confidence": sum(block.confidence for block in page_blocks) / len(page_blocks),
    }


def _render_dpi_for_blocks(blocks: list[DocumentIRBlock]) -> int | None:
    values = [block.render_dpi for block in blocks if block.render_dpi]
    return values[0] if values else None


def _image_payload(image: DocumentPageImage | None) -> dict[str, Any] | None:
    if image is None:
        return None
    return {
        "page": image.page,
        "path": image.path,
        "url": image.url,
        "width": image.width,
        "height": image.height,
        "dpi": image.dpi,
        "sha256": image.sha256,
        "online_allowed": image.online_allowed,
        "source": image.source,
    }


def _block_payload(block: DocumentIRBlock) -> dict[str, Any]:
    return {
        "block_id": block.block_id,
        "page": block.page,
        "reading_order": block.reading_order,
        "text": block.text,
        "bbox": block.bbox,
        "confidence": block.confidence,
        "block_type": block.block_type,
        "section_label": block.section_label,
        "document_kind": block.document_kind,
        "document_region": block.document_region,
        "key_label": block.key_label,
        "value_text": block.value_text,
        "parent_block_id": block.parent_block_id,
        "derived_from_block_ids": block.derived_from_block_ids,
        "table_id": block.table_id,
        "row": block.row,
        "col": block.col,
        "source_engine": block.source_engine,
        "source_page_kind": block.source_page_kind,
        "quality_flags": block.quality_flags,
    }


def _page_blocks_for_payload(blocks: list[DocumentIRBlock], max_blocks: int | None) -> list[DocumentIRBlock]:
    return blocks if max_blocks is None else blocks[: max(0, max_blocks)]


def _render_pdf_pages(source: Path, output_root: Path, *, allow_online: bool) -> dict[int, DocumentPageImage]:
    try:
        import pypdfium2
    except Exception:
        return {}
    rendered: dict[int, DocumentPageImage] = {}
    with pypdfium2.PdfDocument(str(source)) as pdf:
        for index in range(len(pdf)):
            page_number = index + 1
            target = output_root / f"page-{page_number:04d}.png"
            page = pdf[index]
            bitmap = page.render(scale=2)
            image = bitmap.to_pil()
            image.save(target)
            rendered[page_number] = DocumentPageImage(
                page=page_number,
                path=str(target),
                width=image.width,
                height=image.height,
                sha256=_file_sha256(target),
                online_allowed=allow_online,
                source="rendered_pdf_page",
            )
    return rendered


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
