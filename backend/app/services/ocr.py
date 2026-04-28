from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Protocol

from PIL import Image, ImageFilter, ImageOps

from app.core.config import settings
from app.schemas.pipeline import OcrBlock
from app.services.system_config import OcrProfileConfig, load_system_config


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


class ImageOcrEngine(Protocol):
    def extract_blocks(self, image_path: Path, page: int) -> list[OcrBlock]:
        raise NotImplementedError


class LocalOcrEngine:
    def __init__(self, engine_priority: list[str] | None = None) -> None:
        self._engine: object | None = None
        self._engine_name: str | None = None
        self._engine_priority = engine_priority or ["rapidocr", "paddleocr"]

    def extract_blocks(self, image_path: Path, page: int) -> list[OcrBlock]:
        engine = self._load_engine()
        blocks: list[OcrBlock] = []

        if self._engine_name == "rapidocr":
            result, _ = engine(str(image_path))  # type: ignore[misc, operator]
            for item in result or []:
                bbox, text, confidence = item
                if text:
                    blocks.append(
                        OcrBlock(
                            page=page,
                            text=str(text).strip(),
                            bbox=_normalize_bbox(bbox),
                            confidence=float(confidence),
                        )
                    )
            return sorted(blocks, key=lambda item: _bbox_sort_key(item.bbox))

        results = engine.ocr(str(image_path), cls=True)  # type: ignore[attr-defined]
        for page_result in results or []:
            for line in page_result or []:
                bbox, payload = line
                text, confidence = payload
                if text:
                    blocks.append(
                        OcrBlock(
                            page=page,
                            text=str(text).strip(),
                            bbox=_normalize_bbox(bbox),
                            confidence=float(confidence),
                        )
                    )
        return sorted(blocks, key=lambda item: _bbox_sort_key(item.bbox))

    def _load_engine(self) -> object:
        if self._engine is not None:
            return self._engine

        errors: list[ImportError] = []
        for engine_name in self._engine_priority:
            if engine_name == "rapidocr":
                try:
                    from rapidocr_onnxruntime import RapidOCR

                    self._engine = RapidOCR(text_score=0.5)
                    self._engine_name = "rapidocr"
                    return self._engine
                except ImportError as exc:
                    errors.append(exc)
            if engine_name == "paddleocr":
                try:
                    from paddleocr import PaddleOCR

                    self._engine = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
                    self._engine_name = "paddleocr"
                    return self._engine
                except ImportError as exc:
                    errors.append(exc)
        raise RuntimeError("图片和无文本层 PDF 必须安装 RapidOCR 或 PaddleOCR 才能处理。") from (errors[-1] if errors else None)


def ocr_file(
    path: Path,
    payload: bytes,
    *,
    engine: ImageOcrEngine | None = None,
    pdf_text_extractor: Callable[[Path], list[OcrBlock]] | None = None,
    pdf_renderer: Callable[[Path], list[Path]] | None = None,
    ocr_profile: OcrProfileConfig | None = None,
) -> list[OcrBlock]:
    profile = ocr_profile or load_system_config().ocr.profile(settings.ocr_profile)
    suffix = path.suffix.lower()
    if suffix in {".txt", ".text"}:
        return _blocks_from_text(payload.decode("utf-8", errors="ignore"))
    if suffix == ".pdf":
        text_extractor = pdf_text_extractor or _blocks_from_pdf_text_layer
        rendered_pages = pdf_renderer or _render_pdf_pages
        text_blocks = text_extractor(path)
        if text_blocks:
            return text_blocks
        return _blocks_from_images(rendered_pages(path), engine=engine, ocr_profile=profile)
    if suffix in IMAGE_SUFFIXES:
        return _blocks_from_images([path], engine=engine, ocr_profile=profile)
    raise RuntimeError(f"不支持的文件类型：{suffix or 'unknown'}")


def _blocks_from_text(text: str) -> list[OcrBlock]:
    blocks: list[OcrBlock] = []
    for index, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        blocks.append(
            OcrBlock(
                page=1,
                text=line,
                bbox=[0, float(index * 20), 800, float(index * 20 + 18)],
                confidence=0.98,
            )
        )
    if not blocks and text.strip():
        blocks.append(OcrBlock(page=1, text=text.strip(), bbox=[], confidence=0.95))
    return blocks


def _blocks_from_pdf_text_layer(path: Path) -> list[OcrBlock]:
    from pypdf import PdfReader

    blocks: list[OcrBlock] = []
    reader = PdfReader(str(path))
    for page_index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        for line_index, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if line:
                blocks.append(
                    OcrBlock(
                        page=page_index,
                        text=line,
                        bbox=[0, float(line_index * 20), 800, float(line_index * 20 + 18)],
                        confidence=0.90,
                    )
                )
    return blocks


def _render_pdf_pages(path: Path) -> list[Path]:
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover - covered by install/runtime diagnostics
        raise RuntimeError("无文本层 PDF 必须安装 pypdfium2 才能渲染页面后 OCR。") from exc

    page_dir = path.parent / ".pages" / path.stem
    page_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    pdf = pdfium.PdfDocument(str(path))
    try:
        for index in range(len(pdf)):
            page = pdf.get_page(index)
            try:
                profile = load_system_config().ocr.profile(settings.ocr_profile)
                bitmap = page.render(scale=max(1.0, profile.pdf_dpi / 72.0))
                image = bitmap.to_pil()
                page_path = page_dir / f"page_{index + 1:03d}.png"
                image.save(page_path)
                rendered.append(page_path)
            finally:
                page.close()
    finally:
        pdf.close()
    return rendered


def _blocks_from_images(
    image_paths: list[Path],
    *,
    engine: ImageOcrEngine | None = None,
    ocr_profile: OcrProfileConfig | None = None,
) -> list[OcrBlock]:
    profile = ocr_profile or load_system_config().ocr.profile(settings.ocr_profile)
    blocks: list[OcrBlock] = []
    max_workers = settings.ocr_page_workers or profile.max_parallel_pages
    if engine is not None or max_workers <= 1 or len(image_paths) <= 1:
        ocr_engine = engine or LocalOcrEngine(profile.engine_priority)
        for page, image_path in enumerate(image_paths, start=1):
            input_path = _preprocess_image(image_path, profile) if profile.preprocess.enabled else image_path
            page_blocks = ocr_engine.extract_blocks(input_path, page)
            blocks.extend(page_blocks)
    else:
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="eyes-ocr-page") as executor:
            futures = [
                executor.submit(_extract_page_blocks, page, image_path, profile)
                for page, image_path in enumerate(image_paths, start=1)
            ]
            for future in futures:
                blocks.extend(future.result())
    if not blocks:
        raise RuntimeError("OCR 未识别到文本，请检查扫描质量或更换 OCR 引擎。")
    return sorted(blocks, key=lambda item: (item.page, _bbox_sort_key(item.bbox)))


def _extract_page_blocks(page: int, image_path: Path, profile: OcrProfileConfig) -> list[OcrBlock]:
    input_path = _preprocess_image(image_path, profile) if profile.preprocess.enabled else image_path
    return LocalOcrEngine(profile.engine_priority).extract_blocks(input_path, page)


def _preprocess_image(path: Path, profile: OcrProfileConfig) -> Path:
    output_dir = path.parent / ".preprocessed"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{path.stem}_{profile.pdf_dpi}dpi.png"
    if output_path.exists() and output_path.stat().st_mtime >= path.stat().st_mtime:
        return output_path

    try:
        with Image.open(path) as image:
            processed = ImageOps.exif_transpose(image)
            if profile.preprocess.grayscale:
                processed = ImageOps.grayscale(processed)
            if profile.preprocess.autocontrast:
                processed = ImageOps.autocontrast(processed)
            if profile.preprocess.denoise:
                processed = processed.filter(ImageFilter.MedianFilter(size=3))
            if profile.preprocess.threshold:
                gray = processed.convert("L")
                processed = gray.point(lambda value: 255 if value > 180 else 0, mode="1")
            processed.save(output_path)
        return output_path
    except OSError:
        return path


def _normalize_bbox(raw_bbox: object) -> list[float]:
    if not isinstance(raw_bbox, list) or not raw_bbox:
        return []
    if len(raw_bbox) == 4 and all(isinstance(value, (int, float)) for value in raw_bbox):
        return [float(value) for value in raw_bbox]
    points: list[tuple[float, float]] = []
    for point in raw_bbox:
        if (
            isinstance(point, (list, tuple))
            and len(point) >= 2
            and isinstance(point[0], (int, float))
            and isinstance(point[1], (int, float))
        ):
            points.append((float(point[0]), float(point[1])))
    if not points:
        return []
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def _bbox_sort_key(bbox: list[float]) -> tuple[float, float]:
    if len(bbox) < 2:
        return (math.inf, math.inf)
    return (bbox[1], bbox[0])
