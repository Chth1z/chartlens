from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def now_utc() -> datetime:
    return datetime.now(UTC)


class CaseRecord(Base):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    case_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_hash: Mapped[str] = mapped_column(String(64), index=True)
    file_path: Mapped[str] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(32), default="queued")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    ocr_blocks: Mapped[list[OcrBlockRecord]] = relationship(cascade="all, delete-orphan")
    results: Mapped[list[ExtractionResultRecord]] = relationship(cascade="all, delete-orphan")
    audits: Mapped[list[ReviewAuditRecord]] = relationship(cascade="all, delete-orphan")


class OcrBlockRecord(Base):
    __tablename__ = "ocr_blocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), index=True)
    page: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    redacted_text: Mapped[str] = mapped_column(Text)
    bbox: Mapped[list[float]] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)


class DocumentFragmentRecord(Base):
    __tablename__ = "document_fragments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), index=True)
    page: Mapped[int] = mapped_column(Integer)
    reading_order: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    redacted_text: Mapped[str] = mapped_column(Text)
    bbox: Mapped[list[float]] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    section_name: Mapped[str] = mapped_column(String(128), default="基本信息")
    block_type: Mapped[str] = mapped_column(String(32), default="text")
    source_kind: Mapped[str] = mapped_column(String(32), default="ocr")


class ExtractionResultRecord(Base):
    __tablename__ = "extraction_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), index=True)
    field_key: Mapped[str] = mapped_column(String(128), index=True)
    raw_value: Mapped[str | None] = mapped_column(String(512), nullable=True)
    normalized_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox: Mapped[list[float]] = mapped_column(JSON, default=list)
    reasoning_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_required: Mapped[bool] = mapped_column(Boolean, default=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ProcessingRunRecord(Base):
    __tablename__ = "processing_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="running")
    ocr_profile: Mapped[str] = mapped_column(String(64), default="accurate")
    layout_profile: Mapped[str] = mapped_column(String(64), default="clinical_sections")
    llm_profile: Mapped[str] = mapped_column(String(64), default="standard")
    parser_mode: Mapped[str] = mapped_column(String(64), default="ocr")
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    ocr_block_count: Mapped[int] = mapped_column(Integer, default=0)
    fragment_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_ocr_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    low_confidence_block_count: Mapped[int] = mapped_column(Integer, default=0)
    quality_band: Mapped[str] = mapped_column(String(32), default="poor")
    auto_accept_count: Mapped[int] = mapped_column(Integer, default=0)
    review_required_count: Mapped[int] = mapped_column(Integer, default=0)
    unknown_count: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    step_timings: Mapped[dict] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ModelCallLogRecord(Base):
    __tablename__ = "model_call_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    call_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128), default="")
    mode: Mapped[str] = mapped_column(String(32), default="standard")
    field_keys: Mapped[list[str]] = mapped_column(JSON, default=list)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="completed")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class VisionFallbackRequestRecord(Base):
    __tablename__ = "vision_fallback_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), index=True)
    page: Mapped[int] = mapped_column(Integer)
    bbox: Mapped[list[float]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="approved_pending")
    reason: Mapped[str] = mapped_column(Text)
    reviewer: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EvalRunRecord(Base):
    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    eval_run_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    case_count: Mapped[int] = mapped_column(Integer, default=0)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ReviewAuditRecord(Base):
    __tablename__ = "review_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), index=True)
    field_key: Mapped[str] = mapped_column(String(128), index=True)
    old_raw_value: Mapped[str | None] = mapped_column(String(512), nullable=True)
    old_normalized_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    new_raw_value: Mapped[str | None] = mapped_column(String(512), nullable=True)
    new_normalized_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewer: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
