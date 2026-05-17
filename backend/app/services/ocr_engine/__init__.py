"""
OCR Engine Package — Modular OCR pipeline aligned with mature project standards.

This package splits the monolithic intelligent_ocr.py into focused modules:
- types: Data classes (IntelligentOcrBlock, IntelligentOcrResult, RapidOcrPageInput)
- errors: Structured OCR error codes and DirectML auto-recovery
- preprocessing: Image preprocessing (orientation, deskew, CLAHE, denoise, tiling)
- postprocessing: Block dedup, NMS, containment check, line stitching
- payload_parse: JSON/Markdown/PaddleX payload parsing
- bbox_utils: Bounding box geometry utilities (IoU, containment, merge)
- engine_base: Protocol, helpers, engine selection, retry orchestration
- engines/: Individual engine implementations with model singleton pooling
- canonicalize: Hybrid pipeline merge/canonicalization
- observability: Structured timing, quality metrics, trace context
- evaluation: CER/WER computation for regression testing
- concurrency: Page-level parallelism and timeout protection
- model_pool: Thread-safe singleton model cache (eliminates reload per request)
- retry: Exponential backoff with jitter for transient engine failures
- calibration: Temperature-based confidence calibration for better quality routing
"""

from app.services.ocr_engine.types import (
    IntelligentOcrBlock,
    IntelligentOcrResult,
    RapidOcrPageInput,
)
from app.services.ocr_engine.errors import OcrErrorCode, OcrEngineError
from app.services.ocr_engine.engine_base import (
    IntelligentOcrEngine,
    extract_with_intelligent_ocr,
    default_intelligent_ocr_engines,
)
from app.services.ocr_engine.observability import (
    OcrTrace,
    StageMetric,
    trace_stage,
    quality_band,
)
from app.services.ocr_engine.evaluation import (
    character_error_rate,
    word_error_rate,
    evaluate_ocr_output,
    evaluate_page_level,
    evaluate_layout_tables,
)

__all__ = [
    # Core types
    "IntelligentOcrBlock",
    "IntelligentOcrResult",
    "RapidOcrPageInput",
    # Error handling
    "OcrErrorCode",
    "OcrEngineError",
    # Engine protocol & orchestration
    "IntelligentOcrEngine",
    "extract_with_intelligent_ocr",
    "default_intelligent_ocr_engines",
    # Observability
    "OcrTrace",
    "StageMetric",
    "trace_stage",
    "quality_band",
    # Evaluation
    "character_error_rate",
    "word_error_rate",
    "evaluate_ocr_output",
    "evaluate_page_level",
    "evaluate_layout_tables",
]
