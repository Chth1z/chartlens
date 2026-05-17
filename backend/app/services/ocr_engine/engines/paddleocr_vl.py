"""PaddleOCR-VL engine."""
from __future__ import annotations
from pathlib import Path
from app.services.ocr_engine.types import IntelligentOcrResult
from app.services.ocr_engine.engine_base import (
    paddleocr_package_available, preload_torch_for_windows,
    engine_metadata, current_accelerator,
)
from app.services.ocr_engine.payload_parse import result_from_payload


class PaddleOCRVLEngine:
    name = "paddleocr_vl"

    def available(self) -> bool:
        return paddleocr_package_available()

    def unavailable_reason(self) -> str:
        return "Python package 'paddleocr' is not installed in the backend runtime"

    def extract(self, file_path: Path) -> IntelligentOcrResult:
        preload_torch_for_windows()
        from paddleocr import PaddleOCRVL
        pipeline = PaddleOCRVL()
        output = pipeline.predict(input=str(file_path))
        result = result_from_payload(self.name, output, default_confidence=0.88)
        return IntelligentOcrResult(
            engine=result.engine, blocks=result.blocks,
            metadata={**result.metadata, **engine_metadata("PaddleOCR-VL-1.5", "1.5", accelerator=current_accelerator())},
        )
