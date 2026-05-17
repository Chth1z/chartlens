"""PP-StructureV3 engine."""
from __future__ import annotations
import logging
import time
from pathlib import Path
from app.services.ocr_engine.types import IntelligentOcrResult
from app.services.ocr_engine.engine_base import (
    paddleocr_package_available, preload_torch_for_windows,
    engine_metadata, current_accelerator,
)
from app.services.ocr_engine.payload_parse import result_from_payload
from app.services.ocr_engine.model_pool import get_or_create

_log = logging.getLogger(__name__)


class PaddleStructureV3Engine:
    name = "paddle_structure_v3"

    def available(self) -> bool:
        return paddleocr_package_available()

    def unavailable_reason(self) -> str:
        return "Python package 'paddleocr' is not installed in the backend runtime"

    def extract(self, file_path: Path) -> IntelligentOcrResult:
        preload_torch_for_windows()

        def _create():
            import os, sys
            import logging
            logger = logging.getLogger(__name__)
            logger.warning("paddle_structure_v3: _create called. Executable: %s, PATH: %s", sys.executable, os.environ.get("PATH", "")[:500])
            try:
                from paddleocr import PPStructureV3
                return PPStructureV3()
            except Exception as e:
                logger.error("paddle_structure_v3: import failed: %s", e, exc_info=True)
                raise

        pipeline = get_or_create("pp_structure_v3", _create)
        t0 = time.monotonic()
        output = pipeline.predict(input=str(file_path))
        result = result_from_payload(self.name, output, default_confidence=0.86)
        duration_ms = round((time.monotonic() - t0) * 1000, 1)
        _log.info("StructureV3: %s → %d blocks, %.0fms", file_path.name, len(result.blocks), duration_ms)
        return IntelligentOcrResult(
            engine=result.engine, blocks=result.blocks,
            metadata={
                **result.metadata,
                "extract_duration_ms": duration_ms,
                **engine_metadata("PP-StructureV3", accelerator=current_accelerator()),
            },
        )

