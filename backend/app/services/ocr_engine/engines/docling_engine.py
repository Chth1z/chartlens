"""Docling engine."""
from __future__ import annotations
import importlib.util
from pathlib import Path
from app.services.ocr_engine.types import IntelligentOcrResult
from app.services.ocr_engine.engine_base import preload_torch_for_windows
from app.services.ocr_engine.payload_parse import blocks_from_markdown


class DoclingEngine:
    name = "docling"

    def available(self) -> bool:
        return importlib.util.find_spec("docling") is not None

    def unavailable_reason(self) -> str:
        return "Python package 'docling' is not installed in the backend runtime"

    def extract(self, file_path: Path) -> IntelligentOcrResult:
        preload_torch_for_windows()
        from docling.document_converter import DocumentConverter
        result = DocumentConverter().convert(str(file_path))
        markdown = result.document.export_to_markdown()
        blocks = blocks_from_markdown(markdown)
        return IntelligentOcrResult(engine=self.name, blocks=blocks, metadata={"ocr_docling_export": "markdown"})
