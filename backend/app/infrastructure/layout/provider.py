from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.application.layout_analysis import (
    FALLBACK_LAYOUT_MODEL,
    FALLBACK_LAYOUT_PROVIDER,
    LayoutAnalysisProvider,
)
from app.domain.clinical import LayoutRegion
from app.domain.system_config import LayoutProfileConfig


class PaddleLayoutAnalysisProvider:
    provider_name = "pp_structure_v3"

    def __init__(self, *, model_name: str) -> None:
        self.model_name = model_name
        self._model: Any | None = None

    def analyze(self, page_images: list[Path]) -> list[LayoutRegion]:
        if not page_images:
            return []
        model = self._load_model()
        regions: list[LayoutRegion] = []
        for page, image_path in enumerate(page_images, start=1):
            raw_items = _predict_layout(model, image_path)
            for index, item in enumerate(raw_items, start=1):
                region = _layout_region_from_item(item, page=page, index=index)
                if region is not None:
                    regions.append(region)
        return sorted(regions, key=lambda item: (item.page, item.reading_order, item.bbox[1] if len(item.bbox) > 1 else 0))

    def _load_model(self) -> object:
        if self._model is not None:
            return self._model
        try:
            from paddleocr import LayoutDetection
        except ImportError as exc:
            raise RuntimeError("PaddleOCR LayoutDetection is unavailable") from exc
        self._model = LayoutDetection(model_name=self.model_name)
        return self._model


class UnavailableLayoutProvider:
    provider_name = FALLBACK_LAYOUT_PROVIDER
    model_name = FALLBACK_LAYOUT_MODEL

    def analyze(self, page_images: list[Path]) -> list[LayoutRegion]:
        del page_images
        return []


def build_layout_provider(profile: LayoutProfileConfig, *, ocr_profile_name: str) -> LayoutAnalysisProvider:
    for provider_name in profile.provider_priority:
        if provider_name == "pp_structure_v3":
            if importlib.util.find_spec("paddleocr") is None:
                continue
            model_name = profile.layout_models.get(ocr_profile_name) or profile.layout_models.get("accurate") or "PP-DocLayout-M"
            return PaddleLayoutAnalysisProvider(model_name=model_name)
        if provider_name == FALLBACK_LAYOUT_PROVIDER or provider_name == "heuristic_sections":
            return UnavailableLayoutProvider()
    return UnavailableLayoutProvider()


def load_cached_layout_regions(key: str) -> list[LayoutRegion] | None:
    path = _layout_cache_path(key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return [LayoutRegion.model_validate(item) for item in payload.get("regions", [])]
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def save_cached_layout_regions(key: str, regions: list[LayoutRegion]) -> None:
    path = _layout_cache_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps({"regions": [region.model_dump() for region in regions]}, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def layout_cache_key(
    *,
    file_hash: str,
    provider_name: str,
    model_name: str,
    parser_version: str,
    page_images: list[Path],
) -> str:
    image_hashes: list[str] = []
    for image_path in page_images:
        try:
            image_hashes.append(hashlib.sha256(image_path.read_bytes()).hexdigest())
        except OSError:
            image_hashes.append(str(image_path))
    payload = {
        "version": "layout-v1",
        "file_hash": file_hash,
        "provider_name": provider_name,
        "model_name": model_name,
        "parser_version": parser_version,
        "image_hashes": image_hashes,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _layout_cache_path(key: str) -> Path:
    return Path(settings.storage_dir) / "cache" / "layout" / f"{key}.json"


def _predict_layout(model: object, image_path: Path) -> list[object]:
    if hasattr(model, "predict"):
        result = model.predict(str(image_path))
        if isinstance(result, list):
            return result
        return list(result or [])
    if callable(model):
        result = model(str(image_path))
        if isinstance(result, list):
            return result
    return []


def _layout_region_from_item(item: object, *, page: int, index: int) -> LayoutRegion | None:
    data = _item_to_dict(item)
    bbox = data.get("bbox") or data.get("coordinate") or data.get("box") or data.get("poly")
    normalized_bbox = _normalize_bbox(bbox)
    if not normalized_bbox:
        return None
    label = str(data.get("label") or data.get("category") or data.get("type") or data.get("region_type") or "text")
    score = float(data.get("score") or data.get("confidence") or 0.80)
    return LayoutRegion(
        page=page,
        region_id=f"pp-p{page}-{index}",
        bbox=normalized_bbox,
        region_type=_normalize_region_type(label),
        score=max(0.0, min(score, 1.0)),
        reading_order=int(data.get("reading_order") or index),
    )


def _item_to_dict(item: object) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    if hasattr(item, "json"):
        try:
            return json.loads(item.json())
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    if hasattr(item, "to_dict"):
        value = item.to_dict()
        if isinstance(value, dict):
            return value
    return {key: getattr(item, key) for key in ("bbox", "label", "score", "category", "type") if hasattr(item, key)}


def _normalize_region_type(label: str) -> str:
    normalized = label.lower().replace(" ", "_")
    mapping = {
        "document_title": "title",
        "paragraph_title": "title",
        "text": "text",
        "table": "table",
        "list": "list",
        "abstract": "text",
        "header": "header",
        "footer": "footer",
    }
    return mapping.get(normalized, normalized)


def _normalize_bbox(raw_bbox: object) -> list[float]:
    if isinstance(raw_bbox, list) and len(raw_bbox) == 4 and all(isinstance(value, (int, float)) for value in raw_bbox):
        return [float(value) for value in raw_bbox]
    if isinstance(raw_bbox, tuple) and len(raw_bbox) == 4 and all(isinstance(value, (int, float)) for value in raw_bbox):
        return [float(value) for value in raw_bbox]
    points: list[tuple[float, float]] = []
    if isinstance(raw_bbox, list):
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
