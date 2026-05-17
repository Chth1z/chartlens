"""PP-OCRv5 Paddle engine."""
from __future__ import annotations
import logging
import time
from pathlib import Path
from app.services.ocr_engine.types import IntelligentOcrResult
from app.services.ocr_engine.engine_base import (
    paddleocr_package_available, preload_torch_for_windows,
    import_paddle_ocr_class, engine_metadata, current_accelerator,
)
from app.services.ocr_engine.payload_parse import result_from_payload
from app.services.ocr_engine.model_pool import get_or_create

_log = logging.getLogger(__name__)


class PPOCRV5PaddleEngine:
    name = "pp_ocr_v5_paddle"

    def available(self) -> bool:
        return paddleocr_package_available()

    def unavailable_reason(self) -> str:
        return "Python package 'paddleocr' is not installed in the backend runtime"

    def extract(self, file_path: Path) -> IntelligentOcrResult:
        preload_torch_for_windows()

        def _create():
            PaddleOCR = import_paddle_ocr_class()
            return PaddleOCR(ocr_version="PP-OCRv5", lang="ch")

        pipeline = get_or_create("paddleocr_v5_ch", _create)
        t0 = time.monotonic()
        output = pipeline.predict(input=str(file_path))
        result = result_from_payload(self.name, output, default_confidence=0.87)
        duration_ms = round((time.monotonic() - t0) * 1000, 1)
        _log.info("PaddleOCR v5: %s → %d blocks, %.0fms", file_path.name, len(result.blocks), duration_ms)
        return IntelligentOcrResult(
            engine=result.engine, blocks=result.blocks,
            metadata={
                **result.metadata,
                "extract_duration_ms": duration_ms,
                **engine_metadata("PP-OCRv5", "v5", accelerator=current_accelerator()),
            },
        )

