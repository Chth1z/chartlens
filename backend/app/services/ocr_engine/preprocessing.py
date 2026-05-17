"""Enhanced OCR image preprocessing — aligned with mature pipeline standards.

New modes: deskew, auto_orient, adaptive_binarize, clahe, denoise, full_enhance.
Original modes preserved for backward compatibility.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.services.ocr_engine.concurrency import process_pages_parallel
from app.services.ocr_engine.types import RapidOcrPageInput


def preprocess_ocr_image(image, *, preprocess_mode: str):
    """Apply OCR image preprocessing based on mode string."""
    mode = (preprocess_mode or "none").strip().lower()
    image = image.convert("RGB")
    if mode == "none":
        return image

    from PIL import ImageFilter, ImageOps

    if mode == "autocontrast":
        return ImageOps.autocontrast(image, cutoff=1)
    if mode == "autocontrast_sharpen":
        return ImageOps.autocontrast(image, cutoff=1).filter(
            ImageFilter.UnsharpMask(radius=1.2, percent=140, threshold=3))
    if mode == "grayscale_autocontrast":
        return ImageOps.autocontrast(ImageOps.grayscale(image), cutoff=1).convert("RGB")
    if mode == "grayscale_autocontrast_sharpen":
        return ImageOps.autocontrast(ImageOps.grayscale(image), cutoff=1).filter(
            ImageFilter.UnsharpMask(radius=1.0, percent=130, threshold=3)).convert("RGB")
    if mode == "deskew":
        return _deskew_image(image)
    if mode == "auto_orient":
        return _auto_orient_image(image)
    if mode == "adaptive_binarize":
        return _adaptive_binarize(image)
    if mode == "clahe":
        return _clahe_enhance(image)
    if mode == "denoise":
        return _median_denoise(image)
    if mode == "denoise_sharpen":
        return _median_denoise(image).filter(
            ImageFilter.UnsharpMask(radius=1.0, percent=120, threshold=3))
    if mode == "clahe_sharpen":
        return _clahe_enhance(image).filter(
            ImageFilter.UnsharpMask(radius=1.0, percent=120, threshold=3))
    if mode == "full_enhance":
        image = _median_denoise(image)
        image = _clahe_enhance(image)
        return image.filter(ImageFilter.UnsharpMask(radius=1.0, percent=120, threshold=3))
    raise ValueError(f"Unsupported OCR image_preprocess mode: {preprocess_mode}")


def _deskew_image(image):
    try:
        import numpy as np
        gray = np.array(image.convert("L"))
        dx = np.diff(gray.astype(np.float32), axis=1)
        dy = np.diff(gray.astype(np.float32), axis=0)
        dx = np.pad(dx, ((0, 0), (0, 1)), mode="constant")
        dy = np.pad(dy, ((0, 1), (0, 0)), mode="constant")
        magnitude = np.sqrt(dx**2 + dy**2)
        threshold = np.percentile(magnitude, 95)
        edges = magnitude > threshold
        best_angle, best_score = 0.0, 0.0
        for a10 in range(-50, 51, 5):
            angle = a10 / 10.0
            if abs(angle) < 0.01:
                rotated = edges
            else:
                from PIL import Image as PILImage
                ei = PILImage.fromarray((edges * 255).astype(np.uint8))
                rotated = np.array(ei.rotate(-angle, expand=False, fillcolor=0)) > 127
            score = float(np.var(rotated.sum(axis=1).astype(np.float64)))
            if score > best_score:
                best_score, best_angle = score, angle
        if abs(best_angle) < 0.1 or abs(best_angle) > 15.0:
            return image
        return image.rotate(-best_angle, expand=True, fillcolor=(255, 255, 255))
    except Exception:
        return image


def _auto_orient_image(image):
    try:
        import numpy as np
        gray = np.array(image.convert("L"))
        h_var = float(np.var(gray.mean(axis=1)))
        v_var = float(np.var(gray.mean(axis=0)))
        if v_var > h_var * 2.5:
            return image.rotate(90, expand=True, fillcolor=(255, 255, 255))
        return image
    except Exception:
        return image


def _adaptive_binarize(image):
    try:
        import numpy as np
        from PIL import Image as PILImage
        gray = np.array(image.convert("L"))
        hist = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
        total = gray.size
        sum_t = float(np.dot(np.arange(256), hist))
        sum_bg, w_bg, best_t = 0.0, 0.0, 128
        cur_max = 0.0
        for i in range(256):
            w_bg += hist[i]
            if w_bg == 0: continue
            w_fg = total - w_bg
            if w_fg == 0: break
            sum_bg += i * hist[i]
            bv = w_bg * w_fg * (sum_bg / w_bg - (sum_t - sum_bg) / w_fg) ** 2
            if bv > cur_max:
                cur_max, best_t = bv, i
        binary = ((gray > best_t) * 255).astype(np.uint8)
        return PILImage.fromarray(binary).convert("RGB")
    except Exception:
        from PIL import ImageOps
        return ImageOps.autocontrast(image.convert("L"), cutoff=2).convert("RGB")


def _clahe_enhance(image):
    try:
        import numpy as np
        from PIL import Image as PILImage
        gray = np.array(image.convert("L"))
        hist = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
        clip_val = 2.0 * gray.size / 256
        excess = 0.0
        for i in range(256):
            if hist[i] > clip_val:
                excess += hist[i] - clip_val
                hist[i] = clip_val
        hist += excess / 256
        cdf = hist.cumsum()
        cdf_min = cdf[cdf > 0].min() if cdf[cdf > 0].size > 0 else 0
        denom = gray.size - cdf_min
        if denom == 0:
            return image
        lut = ((cdf - cdf_min) / denom * 255).clip(0, 255).astype(np.uint8)
        return PILImage.fromarray(lut[gray]).convert("RGB")
    except Exception:
        from PIL import ImageOps
        return ImageOps.autocontrast(image, cutoff=1)


def _median_denoise(image, size: int = 3):
    from PIL import ImageFilter
    return image.filter(ImageFilter.MedianFilter(size=size))


def load_ocr_image(source: Path, *, preprocess_mode: str):
    from PIL import Image
    image = Image.open(source)
    return preprocess_ocr_image(image, preprocess_mode=preprocess_mode)


def preprocess_ocr_file(source: Path, target: Path, *, preprocess_mode: str) -> None:
    load_ocr_image(source, preprocess_mode=preprocess_mode).save(target)


def iter_rapidocr_page_inputs(
    file_path: Path, *, render_scale: float = 3.0, preprocess_mode: str = "none",
    directml_safe_mode: bool = True, tile_max_side_len: int = 1536, tile_overlap: int = 96,
    page_render_workers: int = 1,
):
    if file_path.suffix.lower() != ".pdf":
        with tempfile.TemporaryDirectory(prefix="eyex-rapidocr-image-", dir=str(file_path.parent)) as tmp_dir:
            if preprocess_mode == "none" and not directml_safe_mode:
                yield RapidOcrPageInput(page=1, image_path=file_path)
                return
            image = load_ocr_image(file_path, preprocess_mode=preprocess_mode)
            if directml_safe_mode:
                yield from _iter_tiled_ocr_inputs(image, tmp_dir=Path(tmp_dir), stem=file_path.stem,
                    page=1, tile_max_side_len=tile_max_side_len, tile_overlap=tile_overlap)
            else:
                ip = Path(tmp_dir) / f"{file_path.stem}.png"
                image.save(ip)
                yield RapidOcrPageInput(page=1, image_path=ip)
        return

    try:
        import pypdfium2
    except Exception as exc:
        raise RuntimeError("pypdfium2 required for PDF OCR with RapidOCR DirectML") from exc

    with tempfile.TemporaryDirectory(prefix="eyex-rapidocr-pages-", dir=str(file_path.parent)) as tmp_dir:
        tmp_dir_path = Path(tmp_dir)
        with pypdfium2.PdfDocument(str(file_path)) as pdf:
            page_count = len(pdf)
        if page_render_workers <= 1 or page_count <= 1:
            for index in range(page_count):
                yield from _render_pdf_page_inputs(
                    file_path,
                    page_index=index,
                    render_scale=render_scale,
                    preprocess_mode=preprocess_mode,
                    directml_safe_mode=directml_safe_mode,
                    tile_max_side_len=tile_max_side_len,
                    tile_overlap=tile_overlap,
                    tmp_dir=tmp_dir_path,
                )
            return

        results = process_pages_parallel(
            list(range(page_count)),
            lambda index: _render_pdf_page_inputs(
                file_path,
                page_index=index,
                render_scale=render_scale,
                preprocess_mode=preprocess_mode,
                directml_safe_mode=directml_safe_mode,
                tile_max_side_len=tile_max_side_len,
                tile_overlap=tile_overlap,
                tmp_dir=tmp_dir_path,
            ),
            max_workers=page_render_workers,
            page_timeout_seconds=0,
            label="pdf_page_render",
        )
        for page_index, page_inputs, error in results:
            if error:
                raise RuntimeError(f"PDF render page {int(page_index) + 1} failed: {error}")
            for item in page_inputs or []:
                yield item


def _render_pdf_page_inputs(
    file_path: Path,
    *,
    page_index: int,
    render_scale: float,
    preprocess_mode: str,
    directml_safe_mode: bool,
    tile_max_side_len: int,
    tile_overlap: int,
    tmp_dir: Path,
) -> list[RapidOcrPageInput]:
    import pypdfium2

    with pypdfium2.PdfDocument(str(file_path)) as pdf:
        pn = page_index + 1
        bm = pdf[page_index].render(scale=render_scale)
    image = preprocess_ocr_image(bm.to_pil(), preprocess_mode=preprocess_mode)
    if directml_safe_mode:
        return list(
            _iter_tiled_ocr_inputs(
                image,
                tmp_dir=tmp_dir,
                stem=f"page-{pn:04d}",
                page=pn,
                tile_max_side_len=tile_max_side_len,
                tile_overlap=tile_overlap,
            )
        )
    ip = tmp_dir / f"page-{pn:04d}.png"
    image.save(ip)
    return [RapidOcrPageInput(page=pn, image_path=ip)]


def _iter_tiled_ocr_inputs(image, *, tmp_dir, stem, page, tile_max_side_len, tile_overlap):
    w, h = image.size
    ts = max(256, int(tile_max_side_len))
    ov = min(max(0, int(tile_overlap)), ts // 2)
    if w <= ts and h <= ts:
        ip = tmp_dir / f"{stem}.png"
        image.save(ip)
        yield RapidOcrPageInput(page=page, image_path=ip)
        return
    for y in _tile_starts(h, tile_size=ts, overlap=ov):
        for x in _tile_starts(w, tile_size=ts, overlap=ov):
            tile = image.crop((x, y, min(w, x + ts), min(h, y + ts)))
            ip = tmp_dir / f"{stem}-y{y:05d}-x{x:05d}.png"
            tile.save(ip)
            yield RapidOcrPageInput(page=page, image_path=ip, offset_x=float(x), offset_y=float(y))


def _tile_starts(length: int, *, tile_size: int, overlap: int) -> list[int]:
    if length <= tile_size:
        return [0]
    step = max(1, tile_size - overlap)
    starts: list[int] = []
    pos = 0
    while pos + tile_size < length:
        starts.append(pos)
        pos += step
    final = max(0, length - tile_size)
    if not starts or starts[-1] != final:
        starts.append(final)
    return starts


# Backward-compatible aliases
_preprocess_ocr_image = preprocess_ocr_image
_load_ocr_image = load_ocr_image
_preprocess_ocr_file = preprocess_ocr_file
_iter_rapidocr_page_inputs = iter_rapidocr_page_inputs
