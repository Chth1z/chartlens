from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class OcrBlock(BaseModel):
    page: int = Field(ge=1)
    text: str
    bbox: list[float] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)


class LayoutRegion(BaseModel):
    page: int = Field(ge=1)
    region_id: str
    bbox: list[float] = Field(default_factory=list)
    region_type: str = "text"
    score: float = Field(ge=0.0, le=1.0, default=0.0)
    reading_order: int = Field(ge=1)


class DocumentFragment(BaseModel):
    page: int = Field(ge=1)
    reading_order: int = Field(ge=1)
    text: str
    bbox: list[float] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    section_name: str = "基本信息"
    block_type: Literal["line", "paragraph", "table", "title", "text", "form_field"] = "paragraph"
    source_kind: Literal["pdf_text", "ocr", "pp_structure", "manual"] = "ocr"
    layout_region_id: str | None = None
    layout_type: str | None = None
    section_confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    parser_version: str = "heuristic_v1"


class OcrQualitySummary(BaseModel):
    page_count: int = 0
    ocr_block_count: int = 0
    fragment_count: int = 0
    avg_ocr_confidence: float = 0.0
    low_confidence_block_count: int = 0
    quality_band: Literal["good", "fair", "poor"] = "poor"
    needs_vision_fallback: bool = False


class EvidenceCandidate(BaseModel):
    field_key: str
    text: str
    page: int
    bbox: list[float] = Field(default_factory=list)
    ocr_confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    score: float = Field(ge=0.0, le=1.0, default=0.0)


class FieldExtractionResult(BaseModel):
    field_key: str
    raw_value: str | None = None
    normalized_code: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    evidence_text: str | None = None
    page: int | None = None
    bbox: list[float] = Field(default_factory=list)
    reasoning_summary: str | None = None
    review_required: bool = True
    error_code: str | None = None


class ExtractionEnvelope(BaseModel):
    case_id: str
    results: list[FieldExtractionResult]
    mode: Literal["standard", "thorough"] = "standard"
    model_name: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class ReviewUpdate(BaseModel):
    field_key: str
    new_raw_value: str | None = None
    new_normalized_code: str | None = None
    reason: str
    reviewer: str


class VisionFallbackRequest(BaseModel):
    page: int = Field(default=1, ge=1)
    bbox: list[float] = Field(default_factory=list)
    reason: str
    reviewer: str
    manual_redaction_confirmed: bool = False


class EvalCase(BaseModel):
    case_id: str
    expected_fields: dict[str, Any] = Field(default_factory=dict)


class EvalRunRequest(BaseModel):
    name: str
    cases: list[EvalCase] = Field(default_factory=list)
