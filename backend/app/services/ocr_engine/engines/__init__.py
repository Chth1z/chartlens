"""OCR engine implementations — each engine in a focused module."""

from app.services.ocr_engine.engines.paddle_structure_v3 import PaddleStructureV3Engine
from app.services.ocr_engine.engines.ppocrv5_paddle import PPOCRV5PaddleEngine
from app.services.ocr_engine.engines.ppocrv5_directml import PPOCRV5OnnxDirectMLEngine
from app.services.ocr_engine.engines.paddleocr_vl import PaddleOCRVLEngine
from app.services.ocr_engine.engines.hybrid_pipeline import PaddleOcrHybridPipelineEngine
from app.services.ocr_engine.engines.docling_engine import DoclingEngine
from app.services.ocr_engine.engines.http_document_ai import (
    HttpDocumentIntelligenceEngine,
    RemotePaddleOCRVLEngine,
)
from app.services.ocr_engine.engines.openai_vision import OpenAIDocumentVisionEngine

__all__ = [
    "PaddleStructureV3Engine",
    "PPOCRV5PaddleEngine",
    "PPOCRV5OnnxDirectMLEngine",
    "PaddleOCRVLEngine",
    "PaddleOcrHybridPipelineEngine",
    "DoclingEngine",
    "HttpDocumentIntelligenceEngine",
    "RemotePaddleOCRVLEngine",
    "OpenAIDocumentVisionEngine",
]
