from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import mimetypes
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from app.core.config_loader import load_ocr_profile
from app.core.settings import settings
from app.domain.models import DocumentIRBlock, DocumentProfile
from app.services.domain_profile import document_ai_prompt, document_kind_for_section
from app.services.ocr_accelerators import _onnx_available_providers, resolve_ocr_device_status


SECTION_SPLIT = re.compile(r"(?P<label>[\u4e00-\u9fffA-Za-z0-9 -]{2,18})\s*[:：]")
MARKDOWN_LINE = re.compile(r"^\s{0,3}(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)?(?P<text>.+?)\s*$")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
DEFAULT_DOCUMENT_PROFILE_ID = "medical_inpatient_zh"


@dataclass(frozen=True)
class IntelligentOcrBlock:
    page: int
    text: str
    bbox: list[float] = field(default_factory=list)
    confidence: float = 0.0
    block_type: str = "text"
    table_id: str | None = None
    row: int | None = None
    col: int | None = None


@dataclass(frozen=True)
class IntelligentOcrResult:
    engine: str
    blocks: list[IntelligentOcrBlock]
    metadata: dict = field(default_factory=dict)

    @property
    def char_count(self) -> int:
        return sum(len(block.text.strip()) for block in self.blocks)

    @property
    def avg_confidence(self) -> float:
        return sum(block.confidence for block in self.blocks) / len(self.blocks) if self.blocks else 0.0


class IntelligentOcrEngine(Protocol):
    name: str

    def available(self) -> bool: ...

    def extract(self, file_path: Path) -> IntelligentOcrResult: ...


def _paddleocr_package_available() -> bool:
    return importlib.util.find_spec("paddleocr") is not None


def _import_paddle_ocr_class():
    from paddleocr import PaddleOCR

    return PaddleOCR


def extract_with_intelligent_ocr(
    file_path: Path,
    aliases: dict[str, list[str]],
    *,
    engines: list[IntelligentOcrEngine] | None = None,
    page_kind: str = "image_ocr",
    document_profile: DocumentProfile | None = None,
) -> tuple[list[DocumentIRBlock], dict]:
    selected_engines = engines if engines is not None else default_intelligent_ocr_engines(page_kind=page_kind, document_profile=document_profile)
    attempted: list[str] = []
    unavailable: list[str] = []
    unavailable_reasons: dict[str, str] = {}
    failures: dict[str, str] = {}
    candidates: list[dict] = []

    for engine in selected_engines:
        if not engine.available():
            unavailable.append(engine.name)
            reason = _engine_unavailable_reason(engine)
            if reason:
                unavailable_reasons[engine.name] = reason
            continue
        attempted.append(engine.name)
        try:
            result = engine.extract(file_path)
        except Exception as exc:
            failures[engine.name] = str(exc)
            continue
        sufficient = _result_is_sufficient(result)
        candidates.append(_candidate_summary(engine.name, result, sufficient=sufficient))
        if sufficient:
            blocks = _blocks_from_intelligent_result(result, aliases, document_profile=document_profile)
            return blocks, {
                "ocr_adapter": "intelligent_document",
                "ocr_engine": result.engine,
                "ocr_intelligent_status": "completed",
                "ocr_attempted_engines": attempted,
                "ocr_unavailable_engines": unavailable,
                "ocr_unavailable_reasons": unavailable_reasons,
                "ocr_engine_errors": failures,
                "ocr_block_count": len(blocks),
                "ocr_char_count": result.char_count,
                "ocr_avg_confidence": result.avg_confidence,
                "ocr_engine_candidates": candidates,
                **result.metadata,
            }
        _record_insufficient_result(engine, result, failures, unavailable_reasons)

    return [], {
        "ocr_adapter": "intelligent_document",
        "ocr_engine": "none",
        "ocr_intelligent_status": "no_engine_result",
        "ocr_attempted_engines": attempted,
        "ocr_unavailable_engines": unavailable,
        "ocr_unavailable_reasons": unavailable_reasons,
        "ocr_engine_errors": failures,
        "ocr_engine_candidates": candidates,
    }


def default_intelligent_ocr_engines(
    page_kind: str = "image_ocr",
    *,
    document_profile: DocumentProfile | None = None,
) -> list[IntelligentOcrEngine]:
    profile_id = document_profile.profile_id if document_profile else settings.document_profile
    registry: dict[str, IntelligentOcrEngine] = {
        "document_ai_http": HttpDocumentIntelligenceEngine(profile_id=profile_id),
        "openai_document_vision": OpenAIDocumentVisionEngine(document_prompt=document_ai_prompt(document_profile)),
        "paddleocr_vl_remote": RemotePaddleOCRVLEngine(profile_id=profile_id),
        "pp_ocr_v5_onnx_directml": PPOCRV5OnnxDirectMLEngine(),
        "pp_ocr_v5_paddle": PPOCRV5PaddleEngine(),
        "paddleocr_vl": PaddleOCRVLEngine(),
        "paddle_structure_v3": PaddleStructureV3Engine(),
        "docling": DoclingEngine(),
    }
    names = _engine_names_for_page_kind(page_kind)
    if page_kind not in {"low_quality", "difficult_scan"}:
        names = [*names, *_engine_names_for_page_kind("low_quality")]
    names = list(dict.fromkeys(names))
    return [registry[name] for name in names if name in registry]


def _engine_names_for_page_kind(page_kind: str) -> list[str]:
    try:
        profile = load_ocr_profile(settings.ocr_profile)
    except Exception:
        return _with_document_sidecar_if_configured(
            ["pp_ocr_v5_paddle", "paddle_structure_v3", "docling", "paddleocr_vl"],
            page_kind,
        )
    for rule in profile.page_router:
        if page_kind in rule.page_kinds:
            return _with_document_sidecar_if_configured(
                [name for name in rule.engines if name != "pdf_text"],
                page_kind,
            )
    enabled = [engine for engine in profile.engines if engine.enabled]
    return _with_document_sidecar_if_configured(
        [engine.engine_id for engine in sorted(enabled, key=lambda item: item.priority)],
        page_kind,
    )


def _with_document_sidecar_if_configured(names: list[str], page_kind: str) -> list[str]:
    if page_kind in {"native_pdf_text", "text"}:
        return names
    if not settings.ocr_document_ai_url:
        return names
    if "document_ai_http" in names or "paddleocr_vl_remote" in names:
        return names
    return ["document_ai_http", *names]


def _result_is_sufficient(result: IntelligentOcrResult) -> bool:
    if not result.blocks:
        return False
    has_structured_blocks = any(
        block.block_type in {"table", "cell", "form_field", "key_value"} for block in result.blocks
    )
    if has_structured_blocks and result.char_count > 0:
        return True
    min_chars = max(1, int(settings.ocr_intelligent_min_chars))
    if result.char_count < min_chars:
        return False
    return result.avg_confidence >= settings.ocr_intelligent_min_confidence


def _engine_unavailable_reason(engine: IntelligentOcrEngine) -> str:
    method = getattr(engine, "unavailable_reason", None)
    if not callable(method):
        return ""
    try:
        return str(method())
    except Exception:
        return ""


def _record_insufficient_result(
    engine: IntelligentOcrEngine,
    result: IntelligentOcrResult,
    failures: dict[str, str],
    unavailable_reasons: dict[str, str],
) -> None:
    sidecar_errors = result.metadata.get("ocr_http_engine_errors", {})
    if isinstance(sidecar_errors, dict):
        for name, error in sidecar_errors.items():
            failures[f"{engine.name}.{name}"] = str(error)

    sidecar_reasons = result.metadata.get("ocr_http_unavailable_reasons", {})
    if isinstance(sidecar_reasons, dict):
        for name, reason in sidecar_reasons.items():
            unavailable_reasons[f"{engine.name}.{name}"] = str(reason)

    if not result.blocks:
        failures.setdefault(engine.name, "engine returned no blocks")
    else:
        failures.setdefault(
            engine.name,
            f"engine result below quality threshold: chars={result.char_count}, confidence={result.avg_confidence:.3f}",
        )


def _candidate_summary(engine_name: str, result: IntelligentOcrResult, *, sufficient: bool) -> dict:
    structured_count = len(
        [
            block
            for block in result.blocks
            if block.block_type in {"table", "cell", "form_field", "key_value", "checkbox", "selection_mark"}
        ]
    )
    return {
        "engine": result.engine or engine_name,
        "route_engine": engine_name,
        "sufficient": sufficient,
        "block_count": len(result.blocks),
        "char_count": result.char_count,
        "avg_confidence": round(result.avg_confidence, 4),
        "structured_block_count": structured_count,
        "quality_band": _quality_band(result.avg_confidence),
        "alternative_blocks": [
            {
                "page": block.page,
                "text": block.text,
                "bbox": block.bbox,
                "confidence": block.confidence,
                "block_type": block.block_type,
                "table_id": block.table_id,
                "row": block.row,
                "col": block.col,
            }
            for block in result.blocks[:5]
        ],
    }


def _quality_band(confidence: float) -> str:
    if confidence >= 0.9:
        return "good"
    if confidence >= 0.75:
        return "fair"
    return "poor"


def _blocks_from_intelligent_result(
    result: IntelligentOcrResult,
    aliases: dict[str, list[str]],
    *,
    document_profile: DocumentProfile | None = None,
) -> list[DocumentIRBlock]:
    blocks: list[DocumentIRBlock] = []
    current_section = "未知"
    for reading_order, source in enumerate(result.blocks, start=1):
        section = _detect_section(source.text, aliases) or current_section
        current_section = section
        blocks.append(
            DocumentIRBlock(
                block_id=_block_id(reading_order, result.engine, source),
                page=max(1, source.page),
                reading_order=reading_order,
                text=source.text,
                bbox=source.bbox,
                confidence=max(0.0, min(1.0, source.confidence)),
                block_type=_normalize_block_type(source.block_type),
                section_id=_section_id(section),
                section_label=section,
                document_kind=document_kind_for_section(section, document_profile),
                table_id=source.table_id,
                row=source.row,
                col=source.col,
                model_name=_optional_metadata_str(result.metadata, "model_name"),
                model_version=_optional_metadata_str(result.metadata, "model_version"),
                accelerator=_optional_metadata_str(result.metadata, "accelerator"),
                engine_version=_optional_metadata_str(result.metadata, "engine_version"),
                route_profile_id=_optional_metadata_str(result.metadata, "route_profile_id") or settings.ocr_profile,
            )
        )
    return blocks


def _optional_metadata_str(metadata: dict, key: str) -> str | None:
    value = metadata.get(key)
    return str(value) if value is not None and str(value).strip() else None


class PaddleStructureV3Engine:
    name = "paddle_structure_v3"

    def available(self) -> bool:
        return _paddleocr_package_available()

    def unavailable_reason(self) -> str:
        return "Python package 'paddleocr' is not installed in the backend runtime"

    def extract(self, file_path: Path) -> IntelligentOcrResult:
        _preload_torch_for_windows()
        from paddleocr import PPStructureV3

        pipeline = PPStructureV3()
        output = pipeline.predict(input=str(file_path))
        result = _result_from_payload(self.name, output, default_confidence=0.86)
        return IntelligentOcrResult(
            engine=result.engine,
            blocks=result.blocks,
            metadata={**result.metadata, **_engine_metadata("PP-StructureV3", accelerator=_current_accelerator())},
        )


class PPOCRV5PaddleEngine:
    name = "pp_ocr_v5_paddle"

    def available(self) -> bool:
        return _paddleocr_package_available()

    def unavailable_reason(self) -> str:
        return "Python package 'paddleocr' is not installed in the backend runtime"

    def extract(self, file_path: Path) -> IntelligentOcrResult:
        _preload_torch_for_windows()
        PaddleOCR = _import_paddle_ocr_class()

        pipeline = PaddleOCR(ocr_version="PP-OCRv5", lang="ch")
        output = pipeline.predict(input=str(file_path))
        result = _result_from_payload(self.name, output, default_confidence=0.87)
        return IntelligentOcrResult(
            engine=result.engine,
            blocks=result.blocks,
            metadata={**result.metadata, **_engine_metadata("PP-OCRv5", "v5", accelerator=_current_accelerator())},
        )


class PPOCRV5OnnxDirectMLEngine:
    name = "pp_ocr_v5_onnx_directml"

    def available(self) -> bool:
        return self.unavailable_reason() == ""

    def unavailable_reason(self) -> str:
        model_dir = settings.ocr_directml_model_dir
        if not model_dir:
            return "EYEX_OCR_DIRECTML_MODEL_DIR is not configured"
        if not Path(model_dir).exists():
            return f"EYEX_OCR_DIRECTML_MODEL_DIR does not exist: {model_dir}"
        model_path = Path(model_dir)
        has_rapidocr_models = all(
            (model_path / name).exists()
            for name in ("ch_PP-OCRv5_det_mobile.onnx", "ch_PP-OCRv5_rec_mobile.onnx")
        )
        has_alias_models = all((model_path / name).exists() for name in ("det.onnx", "rec.onnx"))
        if not has_rapidocr_models and not has_alias_models:
            return "EYEX_OCR_DIRECTML_MODEL_DIR is missing required PP-OCRv5 ONNX files"
        providers = _onnx_available_providers()
        if "DmlExecutionProvider" not in providers:
            return f"ONNX Runtime DmlExecutionProvider is unavailable; providers={providers or ['none']}"
        if importlib.util.find_spec("rapidocr") is None:
            return "Python package 'rapidocr' is not installed for PP-OCRv5 ONNX execution"
        return ""

    def extract(self, file_path: Path) -> IntelligentOcrResult:
        reason = self.unavailable_reason()
        if reason:
            raise RuntimeError(reason)
        from rapidocr import OCRVersion, RapidOCR

        model_dir = Path(settings.ocr_directml_model_dir)
        engine = RapidOCR(
            params={
                "Global.model_root_dir": str(model_dir),
                "EngineConfig.onnxruntime.use_dml": True,
                "Det.ocr_version": OCRVersion.PPOCRV5,
                "Rec.ocr_version": OCRVersion.PPOCRV5,
            }
        )
        blocks: list[IntelligentOcrBlock] = []
        for page, image_input in _iter_rapidocr_page_inputs(file_path):
            output = engine(str(image_input))
            blocks.extend(_blocks_from_rapidocr_output(output, page=page))
        return IntelligentOcrResult(
            engine=self.name,
            blocks=blocks,
            metadata={
                "ocr_raw_block_count": len(blocks),
                **_engine_metadata("PP-OCRv5", "onnx-directml", accelerator="directml"),
            },
        )


class PaddleOCRVLEngine:
    name = "paddleocr_vl"

    def available(self) -> bool:
        return _paddleocr_package_available()

    def unavailable_reason(self) -> str:
        return "Python package 'paddleocr' is not installed in the backend runtime"

    def extract(self, file_path: Path) -> IntelligentOcrResult:
        _preload_torch_for_windows()
        from paddleocr import PaddleOCRVL

        pipeline = PaddleOCRVL()
        output = pipeline.predict(input=str(file_path))
        result = _result_from_payload(self.name, output, default_confidence=0.88)
        return IntelligentOcrResult(
            engine=result.engine,
            blocks=result.blocks,
            metadata={**result.metadata, **_engine_metadata("PaddleOCR-VL-1.5", "1.5", accelerator=_current_accelerator())},
        )


class DoclingEngine:
    name = "docling"

    def available(self) -> bool:
        return importlib.util.find_spec("docling") is not None

    def unavailable_reason(self) -> str:
        return "Python package 'docling' is not installed in the backend runtime"

    def extract(self, file_path: Path) -> IntelligentOcrResult:
        _preload_torch_for_windows()
        from docling.document_converter import DocumentConverter

        result = DocumentConverter().convert(str(file_path))
        document = result.document
        markdown = document.export_to_markdown()
        blocks = _blocks_from_markdown(markdown)
        return IntelligentOcrResult(engine=self.name, blocks=blocks, metadata={"ocr_docling_export": "markdown"})


class HttpDocumentIntelligenceEngine:
    name = "document_ai_http"

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        client_factory: Callable[[], object] | None = None,
        profile_id: str = DEFAULT_DOCUMENT_PROFILE_ID,
    ) -> None:
        self.endpoint = endpoint if endpoint is not None else settings.ocr_document_ai_url
        self.api_key = api_key if api_key is not None else settings.ocr_document_ai_api_key
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else settings.ocr_document_ai_timeout_seconds
        self.client_factory = client_factory
        self.profile_id = profile_id

    def available(self) -> bool:
        return bool(self.endpoint)

    def unavailable_reason(self) -> str:
        return "EYEX_OCR_DOCUMENT_AI_URL is not configured"

    def extract(self, file_path: Path) -> IntelligentOcrResult:
        import httpx

        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        mime_type = _mime_type(file_path)
        client_factory = self.client_factory or (lambda: httpx.Client(timeout=self.timeout_seconds))
        with client_factory() as client:
            with file_path.open("rb") as file_obj:
                response = client.post(
                    self.endpoint,
                    headers=headers,
                    files={"file": (file_path.name, file_obj, mime_type)},
                    data={"profile_id": self.profile_id},
                )
        response.raise_for_status()
        payload = response.json()
        engine_name = payload.get("engine") if isinstance(payload, dict) and payload.get("engine") else self.name
        result = _result_from_payload(str(engine_name), payload, default_confidence=0.9)
        http_metadata = _http_document_metadata(payload)
        return IntelligentOcrResult(
            engine=result.engine,
            blocks=result.blocks,
            metadata={
                **result.metadata,
                **http_metadata,
                "ocr_http_endpoint": self.endpoint,
            },
        )


class RemotePaddleOCRVLEngine(HttpDocumentIntelligenceEngine):
    name = "paddleocr_vl_remote"

    def unavailable_reason(self) -> str:
        return "EYEX_OCR_DOCUMENT_AI_URL is not configured for remote PaddleOCR-VL sidecar"


def _http_document_metadata(payload) -> dict:
    if not isinstance(payload, dict):
        return {}
    metadata = {
        "ocr_http_attempted_engines": _string_list(payload.get("attempted_engines")),
        "ocr_http_unavailable_engines": _string_list(payload.get("unavailable_engines")),
        "ocr_http_unavailable_reasons": _string_dict(payload.get("unavailable_reasons")),
        "ocr_http_engine_errors": _string_dict(payload.get("engine_errors")),
    }
    nested = payload.get("metadata")
    if isinstance(nested, dict):
        metadata["ocr_http_metadata"] = _payload_to_builtin(nested)
    return metadata


def _preload_torch_for_windows() -> None:
    if os.name != "nt" or importlib.util.find_spec("torch") is None:
        return
    try:
        import torch  # noqa: F401
    except Exception:
        return


def _string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _string_dict(value) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items() if str(key).strip() and str(item).strip()}


def _engine_metadata(model_name: str, model_version: str | None = None, *, accelerator: str | None = None) -> dict:
    return {
        "model_name": model_name,
        "model_version": model_version,
        "accelerator": accelerator or _current_accelerator(),
        "engine_version": f"{model_name}:{model_version or 'default'}",
        "route_profile_id": settings.ocr_profile,
    }


def _current_accelerator() -> str:
    try:
        return resolve_ocr_device_status().resolved
    except Exception:
        return settings.ocr_accelerator or "cpu"


class OpenAIDocumentVisionEngine:
    name = "openai_document_vision"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        client_factory: Callable[..., object] | None = None,
        document_prompt: str | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.openai_api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model or settings.ocr_openai_model or settings.openai_model
        self.client_factory = client_factory
        self.document_prompt = document_prompt or document_ai_prompt(None)

    def available(self) -> bool:
        return bool(self.api_key) and importlib.util.find_spec("openai") is not None

    def unavailable_reason(self) -> str:
        if not self.api_key:
            return "EYEX_OPENAI_API_KEY or OPENAI_API_KEY is not configured"
        return "Python package 'openai' is not installed in the backend runtime"

    def extract(self, file_path: Path) -> IntelligentOcrResult:
        from openai import OpenAI

        client_factory = self.client_factory or OpenAI
        client = client_factory(api_key=self.api_key, timeout=settings.openai_timeout_seconds)
        response = client.responses.create(
            model=self.model,
            input=[
                {
                    "role": "user",
                    "content": [
                        _openai_file_content(file_path),
                        {
                            "type": "input_text",
                            "text": self.document_prompt,
                        },
                    ],
                }
            ],
        )
        payload = _json_payload_from_text(getattr(response, "output_text", "") or str(response))
        result = _result_from_payload(self.name, payload, default_confidence=0.82)
        return IntelligentOcrResult(
            engine=f"{self.name}:{self.model}",
            blocks=result.blocks,
            metadata={
                **result.metadata,
                "ocr_openai_model": self.model,
            },
        )


def _openai_file_content(file_path: Path) -> dict:
    data_url = _data_url(file_path)
    if file_path.suffix.lower() in IMAGE_SUFFIXES:
        return {"type": "input_image", "image_url": data_url}
    return {"type": "input_file", "filename": file_path.name, "file_data": data_url}


def _data_url(file_path: Path) -> str:
    return f"data:{_mime_type(file_path)};base64,{base64.b64encode(file_path.read_bytes()).decode('ascii')}"


def _mime_type(file_path: Path) -> str:
    guessed, _ = mimetypes.guess_type(file_path.name)
    if guessed:
        return guessed
    if file_path.suffix.lower() == ".pdf":
        return "application/pdf"
    return "application/octet-stream"


def _json_payload_from_text(text: str):
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    for candidate in _json_candidates(stripped):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return {"blocks": _blocks_from_markdown(stripped)}


def _json_candidates(text: str) -> list[str]:
    candidates = [text]
    object_start = text.find("{")
    object_end = text.rfind("}")
    if object_start >= 0 and object_end > object_start:
        candidates.append(text[object_start : object_end + 1])
    array_start = text.find("[")
    array_end = text.rfind("]")
    if array_start >= 0 and array_end > array_start:
        candidates.append(text[array_start : array_end + 1])
    return candidates


def _result_from_payload(engine: str, payload, *, default_confidence: float) -> IntelligentOcrResult:
    raw_blocks = list(_iter_payload_blocks(_payload_to_builtin(payload), default_confidence=default_confidence))
    return IntelligentOcrResult(
        engine=engine,
        blocks=raw_blocks,
        metadata={"ocr_raw_block_count": len(raw_blocks)},
    )


def _payload_to_builtin(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _payload_to_builtin(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_payload_to_builtin(item) for item in value]
    for method_name in ("to_dict", "json", "to_json", "export"):
        method = getattr(value, method_name, None)
        if callable(method):
            try:
                return _payload_to_builtin(method())
            except Exception:
                pass
    if hasattr(value, "__dict__"):
        return _payload_to_builtin(vars(value))
    return str(value)


def _iter_payload_blocks(payload, *, default_confidence: float):
    if isinstance(payload, str):
        yield from _blocks_from_markdown(payload, confidence=default_confidence)
        return
    if isinstance(payload, list):
        for item in payload:
            yield from _iter_payload_blocks(item, default_confidence=default_confidence)
        return
    if not isinstance(payload, dict):
        return

    if "blocks" in payload:
        blocks = payload.get("blocks")
        if isinstance(blocks, list):
            for item in blocks:
                yield from _iter_payload_blocks(item, default_confidence=default_confidence)
        return

    overall_ocr_res = payload.get("overall_ocr_res")
    if isinstance(overall_ocr_res, dict):
        page = _extract_int(payload, ("page", "page_id", "page_index", "page_num"), default=1)
        yield from _blocks_from_rec_text_payload(overall_ocr_res, page=max(1, page), default_confidence=default_confidence)
        return

    if isinstance(payload.get("rec_texts"), list):
        page = _extract_int(payload, ("page", "page_id", "page_index", "page_num"), default=1)
        yield from _blocks_from_rec_text_payload(payload, page=max(1, page), default_confidence=default_confidence)
        return

    text = _extract_text(payload)
    if text:
        page = _extract_int(payload, ("page", "page_id", "page_index", "page_num"), default=1)
        if page == 0:
            page = 1
        block_type = _extract_block_type(payload)
        yield IntelligentOcrBlock(
            page=page,
            text=text,
            bbox=_extract_bbox(payload),
            confidence=_extract_confidence(payload, default_confidence),
            block_type=block_type,
            table_id=_extract_optional_str(payload, ("table_id", "tableId")),
            row=_extract_optional_int(payload, ("row", "row_index", "row_id")),
            col=_extract_optional_int(payload, ("col", "column", "col_index", "column_index")),
        )

    for value in payload.values():
        if isinstance(value, (list, dict)):
            yield from _iter_payload_blocks(value, default_confidence=default_confidence)


def _blocks_from_markdown(markdown: str, *, confidence: float = 0.8) -> list[IntelligentOcrBlock]:
    blocks: list[IntelligentOcrBlock] = []
    for line in markdown.splitlines():
        match = MARKDOWN_LINE.match(line)
        if not match:
            continue
        text = match.group("text").strip()
        if not text or set(text) <= {"-", "|", " "}:
            continue
        block_type = "table" if "|" in text else "text"
        blocks.append(IntelligentOcrBlock(page=1, text=text, confidence=confidence, block_type=block_type))
    return blocks


def _blocks_from_rec_text_payload(payload: dict, *, page: int, default_confidence: float):
    texts = payload.get("rec_texts")
    if not isinstance(texts, list):
        return
    scores = payload.get("rec_scores") if isinstance(payload.get("rec_scores"), list) else []
    polys = payload.get("rec_polys") if isinstance(payload.get("rec_polys"), list) else []
    boxes = payload.get("rec_boxes") if isinstance(payload.get("rec_boxes"), list) else []
    for index, raw_text in enumerate(texts):
        if not isinstance(raw_text, str):
            continue
        text = _clean_text(raw_text)
        if not text:
            continue
        score = scores[index] if index < len(scores) and _is_number(scores[index]) else default_confidence
        bbox_source = polys[index] if index < len(polys) else boxes[index] if index < len(boxes) else None
        yield IntelligentOcrBlock(
            page=page,
            text=text,
            bbox=_parse_bbox(bbox_source),
            confidence=max(0.0, min(1.0, float(score))),
            block_type="text",
        )


def _iter_rapidocr_page_inputs(file_path: Path):
    if file_path.suffix.lower() != ".pdf":
        yield 1, file_path
        return

    try:
        import pypdfium2
    except Exception as exc:
        raise RuntimeError("Python package 'pypdfium2' is required to OCR PDF files with RapidOCR DirectML") from exc

    with tempfile.TemporaryDirectory(prefix="eyex-rapidocr-pages-", dir=str(file_path.parent)) as tmp_dir:
        with pypdfium2.PdfDocument(str(file_path)) as pdf:
            for index in range(len(pdf)):
                page_number = index + 1
                page = pdf[index]
                bitmap = page.render(scale=2.0)
                image_path = Path(tmp_dir) / f"page-{page_number:04d}.png"
                bitmap.to_pil().save(image_path)
                yield page_number, image_path


def _blocks_from_rapidocr_output(output, *, page: int = 1) -> list[IntelligentOcrBlock]:
    payload = output[0] if isinstance(output, tuple) and len(output) >= 1 else output
    if isinstance(payload, list):
        blocks = []
        for item in payload:
            try:
                points, text, score = item
            except Exception:
                continue
            if not str(text).strip():
                continue
            blocks.append(
                IntelligentOcrBlock(
                    page=page,
                    text=str(text).strip(),
                    bbox=_parse_polygon(points),
                    confidence=_bounded_float(score, default=0.0),
                    block_type="text",
                )
            )
        return blocks

    raw_texts = getattr(payload, "txts", None)
    if raw_texts is None:
        raw_texts = getattr(payload, "rec_texts", None)
    texts = _as_list(raw_texts)
    if not texts:
        return []
    boxes = getattr(payload, "boxes", None)
    if boxes is None:
        boxes = getattr(payload, "dt_boxes", None)
    box_items = _as_list(boxes)
    raw_scores = getattr(payload, "scores", None)
    if raw_scores is None:
        raw_scores = getattr(payload, "rec_scores", None)
    scores = _as_list(raw_scores)

    blocks = []
    for index, text in enumerate(texts):
        cleaned = _clean_text(str(text))
        if not cleaned:
            continue
        points = box_items[index] if index < len(box_items) else []
        score = scores[index] if index < len(scores) else 0.0
        blocks.append(
            IntelligentOcrBlock(
                page=page,
                text=cleaned,
                bbox=_parse_polygon(points),
                confidence=_bounded_float(score, default=0.0),
                block_type="text",
            )
        )
    return blocks


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        return list(value)
    except TypeError:
        return []


def _bounded_float(value, *, default: float) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = default
    return max(0.0, min(1.0, parsed))


def _extract_text(payload: dict) -> str:
    for key in ("text", "rec_text", "content", "markdown", "md", "html"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return _clean_text(value)
    return ""


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _extract_block_type(payload: dict) -> str:
    raw = str(payload.get("block_type") or payload.get("type") or payload.get("label") or "text").lower()
    if "table" in raw:
        return "table"
    if "cell" in raw:
        return "cell"
    if "title" in raw or "header" in raw:
        return "title"
    if "key" in raw and "value" in raw:
        return "key_value"
    if "form" in raw:
        return "form_field"
    return "text"


def _extract_bbox(payload: dict) -> list[float]:
    for key in ("bbox", "box", "coordinate", "rect"):
        value = payload.get(key)
        parsed = _parse_bbox(value)
        if parsed:
            return parsed
    for key in ("poly", "polygon", "points"):
        value = payload.get(key)
        parsed = _parse_polygon(value)
        if parsed:
            return parsed
    return []


def _parse_bbox(value) -> list[float]:
    if isinstance(value, (list, tuple)) and len(value) == 4 and all(_is_number(item) for item in value):
        return [float(item) for item in value]
    return _parse_polygon(value)


def _parse_polygon(value) -> list[float]:
    if not isinstance(value, (list, tuple)):
        to_list = getattr(value, "tolist", None)
        if callable(to_list):
            value = to_list()
    if not isinstance(value, (list, tuple)) or not value:
        return []
    points = value
    if all(_is_number(item) for item in points) and len(points) >= 4:
        xs = [float(item) for index, item in enumerate(points) if index % 2 == 0]
        ys = [float(item) for index, item in enumerate(points) if index % 2 == 1]
        return [min(xs), min(ys), max(xs), max(ys)]
    try:
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
    except Exception:
        return []
    return [min(xs), min(ys), max(xs), max(ys)]


def _extract_confidence(payload: dict, default: float) -> float:
    for key in ("confidence", "score", "rec_score", "prob"):
        value = payload.get(key)
        if _is_number(value):
            return max(0.0, min(1.0, float(value)))
    return default


def _extract_int(payload: dict, keys: tuple[str, ...], *, default: int) -> int:
    for key in keys:
        value = payload.get(key)
        if _is_number(value):
            return int(value)
    return default


def _extract_optional_int(payload: dict, keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = payload.get(key)
        if _is_number(value):
            return int(value)
    return None


def _extract_optional_str(payload: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _normalize_block_type(block_type: str) -> str:
    if block_type in {
        "line",
        "paragraph",
        "table",
        "title",
        "text",
        "form_field",
        "cell",
        "checkbox",
        "selection_mark",
        "key_value",
    }:
        return block_type
    return "text"


def _block_id(reading_order: int, engine: str, block: IntelligentOcrBlock) -> str:
    digest = hashlib.sha1(f"{engine}:{block.page}:{block.block_type}:{block.text}:{block.row}:{block.col}".encode("utf-8")).hexdigest()
    return f"b{reading_order:04d}-{digest[:8]}"


def _detect_section(text: str, aliases: dict[str, list[str]]) -> str | None:
    prefix = text[:40]
    for label, names in aliases.items():
        for alias in names:
            if prefix.startswith(alias) or re.match(rf"^\s*{re.escape(alias)}\s*[:：]", prefix):
                return label
    match = SECTION_SPLIT.match(prefix)
    if match:
        found = match.group("label").strip()
        for label, names in aliases.items():
            if found in names:
                return label
    return None


def _section_id(label: str) -> str:
    return hashlib.sha1(label.encode("utf-8")).hexdigest()[:12]
