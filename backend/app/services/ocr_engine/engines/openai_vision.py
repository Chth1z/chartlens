"""OpenAI Document Vision engine."""
from __future__ import annotations
import base64
import importlib.util
import json
import mimetypes
import os
import re
from pathlib import Path
from app.core.settings import settings
from app.services.domain_profile import document_ai_prompt
from app.services.ocr_engine.types import IntelligentOcrResult
from app.services.ocr_engine.payload_parse import result_from_payload, blocks_from_markdown

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


class OpenAIDocumentVisionEngine:
    name = "openai_document_vision"

    def __init__(self, api_key=None, model=None, client_factory=None, document_prompt=None):
        self.api_key = api_key if api_key is not None else settings.openai_api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model or settings.ocr_openai_model or settings.openai_model
        self.client_factory = client_factory
        self.document_prompt = document_prompt or document_ai_prompt(None)

    def available(self):
        return bool(self.api_key) and importlib.util.find_spec("openai") is not None

    def unavailable_reason(self):
        if not self.api_key:
            return "EYEX_OPENAI_API_KEY or OPENAI_API_KEY is not configured"
        return "Python package 'openai' is not installed in the backend runtime"

    def extract(self, file_path: Path) -> IntelligentOcrResult:
        from openai import OpenAI
        factory = self.client_factory or OpenAI
        client = factory(api_key=self.api_key, timeout=settings.openai_timeout_seconds)
        response = client.responses.create(
            model=self.model,
            input=[{"role": "user", "content": [
                _openai_file_content(file_path),
                {"type": "input_text", "text": self.document_prompt},
            ]}],
        )
        payload = _json_payload_from_text(getattr(response, "output_text", "") or str(response))
        result = result_from_payload(self.name, payload, default_confidence=0.82)
        return IntelligentOcrResult(
            engine=f"{self.name}:{self.model}", blocks=result.blocks,
            metadata={**result.metadata, "ocr_openai_model": self.model})


def _openai_file_content(fp):
    url = f"data:{_mime(fp)};base64,{base64.b64encode(fp.read_bytes()).decode('ascii')}"
    if fp.suffix.lower() in IMAGE_SUFFIXES:
        return {"type": "input_image", "image_url": url}
    return {"type": "input_file", "filename": fp.name, "file_data": url}


def _mime(fp):
    g, _ = mimetypes.guess_type(fp.name)
    if g: return g
    return "application/pdf" if fp.suffix.lower() == ".pdf" else "application/octet-stream"


def _json_payload_from_text(text):
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
    for c in _json_candidates(s):
        try: return json.loads(c)
        except json.JSONDecodeError: continue
    return {"blocks": blocks_from_markdown(s)}


def _json_candidates(text):
    cs = [text]
    os_start, oe = text.find("{"), text.rfind("}")
    if os_start >= 0 and oe > os_start: cs.append(text[os_start:oe + 1])
    as_start, ae = text.find("["), text.rfind("]")
    if as_start >= 0 and ae > as_start: cs.append(text[as_start:ae + 1])
    return cs
