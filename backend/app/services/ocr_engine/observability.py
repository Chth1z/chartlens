"""OCR observability — structured timing, quality metrics, and trace context.

Aligned with production OCR pipelines: Surya uses per-page timing,
MinerU tracks stage-level metrics, Docling reports confidence distributions.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StageMetric:
    """Timing and quality for a single OCR processing stage."""
    stage: str
    engine: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    duration_ms: float = 0.0
    block_count: int = 0
    char_count: int = 0
    avg_confidence: float = 0.0
    status: str = "pending"  # pending, completed, failed, skipped, timeout
    error: str = ""
    page_metrics: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "engine": self.engine,
            "duration_ms": round(self.duration_ms, 1),
            "block_count": self.block_count,
            "char_count": self.char_count,
            "avg_confidence": round(self.avg_confidence, 4),
            "status": self.status,
            "error": self.error[:500] if self.error else "",
            "page_metrics": self.page_metrics,
        }


@dataclass
class OcrTrace:
    """Full trace context for an OCR extraction run."""
    trace_id: str = ""
    file_name: str = ""
    file_size: int = 0
    page_count: int = 0
    started_at: float = 0.0
    finished_at: float = 0.0
    total_duration_ms: float = 0.0
    stages: list[StageMetric] = field(default_factory=list)
    selected_engine: str = ""
    result_block_count: int = 0
    result_char_count: int = 0
    result_avg_confidence: float = 0.0
    quality_band: str = "unknown"
    error: str = ""

    def start(self) -> None:
        self.started_at = time.monotonic()

    def finish(self) -> None:
        self.finished_at = time.monotonic()
        self.total_duration_ms = (self.finished_at - self.started_at) * 1000

    def add_stage(self, stage: StageMetric) -> None:
        self.stages.append(stage)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "file_name": self.file_name,
            "file_size": self.file_size,
            "page_count": self.page_count,
            "total_duration_ms": round(self.total_duration_ms, 1),
            "selected_engine": self.selected_engine,
            "result_block_count": self.result_block_count,
            "result_char_count": self.result_char_count,
            "result_avg_confidence": round(self.result_avg_confidence, 4),
            "quality_band": self.quality_band,
            "error": self.error[:500] if self.error else "",
            "stages": [s.to_dict() for s in self.stages],
        }


@contextmanager
def trace_stage(trace: OcrTrace, stage_name: str, engine_name: str = ""):
    """Context manager to time an OCR stage and record metrics."""
    metric = StageMetric(stage=stage_name, engine=engine_name, started_at=time.monotonic())
    try:
        yield metric
        metric.status = "completed"
    except TimeoutError:
        metric.status = "timeout"
        metric.error = "stage exceeded timeout"
        raise
    except Exception as exc:
        from app.services.ocr_engine.errors import OcrErrorCode

        metric.status = "timeout" if OcrErrorCode.classify(exc) in {
            OcrErrorCode.TIMEOUT,
            OcrErrorCode.DIRECTML_TIMEOUT,
            OcrErrorCode.PAGE_TIMEOUT,
        } else "failed"
        metric.error = str(exc)[:500]
        raise
    finally:
        metric.finished_at = time.monotonic()
        metric.duration_ms = (metric.finished_at - metric.started_at) * 1000
        trace.add_stage(metric)


def quality_band(avg_confidence: float) -> str:
    """Classify OCR quality into bands."""
    if avg_confidence >= 0.95:
        return "excellent"
    if avg_confidence >= 0.9:
        return "good"
    if avg_confidence >= 0.75:
        return "fair"
    if avg_confidence >= 0.5:
        return "poor"
    return "very_poor"


def confidence_distribution(confidences: list[float]) -> dict[str, int]:
    """Bin confidence scores for distribution analysis."""
    bins = {"0.95+": 0, "0.90-0.95": 0, "0.75-0.90": 0, "0.50-0.75": 0, "<0.50": 0}
    for c in confidences:
        if c >= 0.95:
            bins["0.95+"] += 1
        elif c >= 0.90:
            bins["0.90-0.95"] += 1
        elif c >= 0.75:
            bins["0.75-0.90"] += 1
        elif c >= 0.50:
            bins["0.50-0.75"] += 1
        else:
            bins["<0.50"] += 1
    return bins


def page_quality_metrics(blocks, page: int) -> dict[str, Any]:
    """Compute quality metrics for a single page's OCR blocks."""
    page_blocks = [b for b in blocks if b.page == page]
    if not page_blocks:
        return {"page": page, "block_count": 0, "char_count": 0, "avg_confidence": 0.0, "quality_band": "unknown"}
    char_count = sum(len(b.text.strip()) for b in page_blocks)
    avg_conf = sum(b.confidence for b in page_blocks) / len(page_blocks)
    return {
        "page": page,
        "block_count": len(page_blocks),
        "char_count": char_count,
        "avg_confidence": round(avg_conf, 4),
        "quality_band": quality_band(avg_conf),
        "confidence_distribution": confidence_distribution([b.confidence for b in page_blocks]),
    }
