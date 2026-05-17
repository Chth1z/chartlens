"""OCR engine data types — extracted from intelligent_ocr.py for modularity."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class IntelligentOcrBlock:
    page: int
    text: str
    bbox: list[float] = field(default_factory=list)
    confidence: float = 0.0
    block_type: str = "text"
    table_id: str | None = None
    row: int | None = None
    col: int | None = None
    row_span: int = 1
    col_span: int = 1
    stage_source: str | None = None
    candidate_id: str | None = None
    candidate_group_id: str | None = None
    conflict_flags: list[str] = field(default_factory=list)
    canonical_source_ids: list[str] = field(default_factory=list)
    layout_region_id: str | None = None
    line_group_id: str | None = None
    coordinate_system: str | None = None
    merge_confidence: float | None = None
    merge_flags: list[str] = field(default_factory=list)
    model_name: str | None = None
    model_version: str | None = None
    model_variant: str | None = None
    render_dpi: int | None = None
    preprocess_profile: str | None = None


@dataclass(frozen=True)
class IntelligentOcrResult:
    engine: str
    blocks: list[IntelligentOcrBlock]
    metadata: dict = field(default_factory=dict)

    @property
    def char_count(self) -> int:
        return sum(len(block.text.strip()) for block in self.blocks)

    @property
    def avg_confidence(self) -> float:
        return sum(block.confidence for block in self.blocks) / len(self.blocks) if self.blocks else 0.0


@dataclass(frozen=True)
class RapidOcrPageInput:
    page: int
    image_path: Path
    offset_x: float = 0.0
    offset_y: float = 0.0
