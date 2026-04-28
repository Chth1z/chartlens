from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from app.domain.clinical import LayoutRegion, OcrBlock


SECTION_CLASSIFIER_VERSION = "clinical_section_v1"
LAYOUT_PARSER_VERSION = f"hybrid_layout_v2:{SECTION_CLASSIFIER_VERSION}"
FALLBACK_LAYOUT_PROVIDER = "fallback_heuristic"
FALLBACK_LAYOUT_MODEL = "heuristic"


class LayoutAnalysisProvider(Protocol):
    provider_name: str
    model_name: str

    def analyze(self, page_images: list[Path]) -> list[LayoutRegion]:
        raise NotImplementedError


def fallback_regions_from_blocks(blocks: Iterable[OcrBlock]) -> list[LayoutRegion]:
    regions: list[LayoutRegion] = []
    blocks_by_page: dict[int, list[OcrBlock]] = {}
    for block in blocks:
        blocks_by_page.setdefault(block.page, []).append(block)
    for order, (page, page_blocks) in enumerate(sorted(blocks_by_page.items()), start=1):
        bbox = _merge_bboxes([block.bbox for block in page_blocks]) or [0.0, 0.0, 800.0, 1200.0]
        avg_confidence = sum(block.confidence for block in page_blocks) / len(page_blocks) if page_blocks else 0.55
        regions.append(
            LayoutRegion(
                page=page,
                region_id=f"fallback-p{page}-content",
                bbox=bbox,
                region_type="text",
                score=max(0.45, min(avg_confidence, 0.80)),
                reading_order=order,
            )
        )
    return regions


def _block_sort_key(block: OcrBlock) -> tuple[int, float, float]:
    if len(block.bbox) >= 2:
        return (block.page, block.bbox[1], block.bbox[0])
    return (block.page, float("inf"), float("inf"))


def _merge_bboxes(bboxes: list[list[float]]) -> list[float]:
    valid = [bbox for bbox in bboxes if len(bbox) >= 4]
    if not valid:
        return []
    return [min(bbox[0] for bbox in valid), min(bbox[1] for bbox in valid), max(bbox[2] for bbox in valid), max(bbox[3] for bbox in valid)]
