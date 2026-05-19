"""Multimodal context builder for vision-capable evidence collection.

When EYEX_MULTIMODAL_EVIDENCE=true and the model supports vision input,
this module renders source PDF pages to images and attaches them to the
DocumentContext for inclusion in the evidence-first prompt.
"""
from __future__ import annotations

import base64
import hashlib
import logging
from pathlib import Path
from typing import Any

from app.core.settings import settings
from app.domain.models import DocumentContext, DocumentContextPage, DocumentPageImage

logger = logging.getLogger(__name__)


def multimodal_enabled() -> bool:
    """Check if multimodal evidence collection is enabled."""
    return getattr(settings, "multimodal_evidence", False)


def enrich_context_with_images(
    context: DocumentContext,
    source_file: Path | None = None,
) -> DocumentContext:
    """Attach page images to DocumentContext pages when multimodal is enabled.

    Renders PDF pages to PNG images (or uses existing image files) and
    populates the `image` field on each DocumentContextPage.

    Returns the context unchanged if:
    - multimodal_evidence is disabled
    - source_file is None or doesn't exist
    - rendering fails
    """
    if not multimodal_enabled():
        return context

    if source_file is None or not source_file.exists():
        return context

    max_pages = min(settings.multimodal_max_pages, len(context.pages))
    if max_pages <= 0:
        return context

    suffix = source_file.suffix.lower()

    try:
        if suffix == ".pdf":
            page_images = _render_pdf_pages(source_file, max_pages)
        elif suffix in (".png", ".jpg", ".jpeg"):
            page_images = _load_image_file(source_file)
        else:
            return context
    except Exception as exc:
        logger.warning("Failed to render page images for multimodal: %s", exc)
        return context

    if not page_images:
        return context

    # Attach images to context pages
    updated_pages: list[DocumentContextPage] = []
    for page in context.pages:
        if page.page in page_images:
            image_data = page_images[page.page]
            page_image = DocumentPageImage(
                page=page.page,
                path=str(image_data.get("path", "")),
                width=image_data.get("width"),
                height=image_data.get("height"),
                dpi=image_data.get("dpi", 150),
                sha256=image_data.get("sha256"),
                online_allowed=True,
                source="rendered_page",
            )
            updated_pages.append(page.model_copy(update={"image": page_image}))
        else:
            updated_pages.append(page)
    
    return context.model_copy(update={
        "pages": updated_pages,
        "metadata": {**context.metadata, "multimodal_images_attached": len(page_images)},
    })


def page_image_to_base64_url(image_path: str) -> str | None:
    """Read an image file and return a base64 data URL for LLM API."""
    path = Path(image_path)
    if not path.exists():
        return None

    try:
        data = path.read_bytes()
        suffix = path.suffix.lower()
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(
            suffix, "image/png"
        )
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{encoded}"
    except Exception:
        return None


def _render_pdf_pages(pdf_path: Path, max_pages: int) -> dict[int, dict[str, Any]]:
    """Render PDF pages to PNG images using pypdfium2 if available."""
    page_images: dict[int, dict[str, Any]] = {}

    try:
        import pypdfium2
    except ImportError:
        logger.debug("pypdfium2 not available for PDF rendering")
        return page_images

    cache_dir = settings.storage_dir / "page_images"
    cache_dir.mkdir(parents=True, exist_ok=True)

    file_hash = hashlib.sha256(pdf_path.read_bytes()[:4096]).hexdigest()[:12]

    try:
        pdf = pypdfium2.PdfDocument(str(pdf_path))
        num_pages = min(len(pdf), max_pages)

        for page_num in range(num_pages):
            page = pdf[page_num]
            # Render at 150 DPI for balance of quality and size
            bitmap = page.render(scale=150 / 72)
            pil_image = bitmap.to_pil()

            image_filename = f"{file_hash}_p{page_num + 1}.png"
            image_path = cache_dir / image_filename

            if not image_path.exists():
                pil_image.save(str(image_path), "PNG", optimize=True)

            page_images[page_num + 1] = {
                "path": str(image_path),
                "width": pil_image.width,
                "height": pil_image.height,
                "dpi": 150,
                "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest()[:16],
            }

        pdf.close()
    except Exception as exc:
        logger.warning("PDF page rendering failed: %s", exc)

    return page_images


def _load_image_file(image_path: Path) -> dict[int, dict[str, Any]]:
    """Load a single image file as page 1."""
    try:
        data = image_path.read_bytes()
        sha = hashlib.sha256(data[:4096]).hexdigest()[:16]
        return {
            1: {
                "path": str(image_path),
                "width": None,
                "height": None,
                "dpi": None,
                "sha256": sha,
            }
        }
    except Exception:
        return {}
