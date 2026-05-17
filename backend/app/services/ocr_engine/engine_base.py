"""OCR engine base — Protocol, helpers, engine selection and extraction orchestration."""

from __future__ import annotations

import hashlib
import importlib.util
import re
import time
from pathlib import Path
from typing import Any, Protocol

from app.core.config_loader import load_ocr_profile
from app.core.settings import settings
from app.domain.models import DocumentIRBlock, DocumentProfile, OcrProfile
from app.services.domain_profile import document_ai_prompt, document_kind_for_section
from app.services.ocr_accelerators import resolve_ocr_device_status
from app.services.ocr_engine.concurrency import run_with_timeout
from app.services.ocr_engine.observability import OcrTrace, StageMetric, page_quality_metrics, quality_band, trace_stage
from app.services.ocr_engine.types import IntelligentOcrBlock, IntelligentOcrResult
from app.services.ocr_engine.errors import OcrErrorCode, OcrEngineError

SECTION_SPLIT = re.compile(r"(?P<label>[\u4e00-\u9fffA-Za-z0-9 -]{2,18})\s*[:：]")
DEFAULT_DOCUMENT_PROFILE_ID = "medical_inpatient_zh"


class IntelligentOcrEngine(Protocol):
    name: str
    def available(self) -> bool: ...
    def extract(self, file_path: Path) -> IntelligentOcrResult: ...


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_with_intelligent_ocr(
    file_path: Path,
    aliases: dict[str, list[str]],
    *,
    engines: list[IntelligentOcrEngine] | None = None,
    page_kind: str = "image_ocr",
    document_profile: DocumentProfile | None = None,
) -> tuple[list[DocumentIRBlock], dict]:
    from app.services.ocr_engine.retry import retry_with_backoff

    selected_engines = engines if engines is not None else default_intelligent_ocr_engines(page_kind=page_kind, document_profile=document_profile)
    attempted: list[str] = []
    unavailable: list[str] = []
    unavailable_reasons: dict[str, str] = {}
    failures: dict[str, str] = {}
    candidates: list[dict] = []
    trace = _start_ocr_trace(file_path)
    # Track best partial result for graceful degradation
    best_partial: tuple[IntelligentOcrResult, str] | None = None
    best_partial_score: tuple[int, float] = (0, 0.0)

    for engine in selected_engines:
        if not engine.available():
            unavailable.append(engine.name)
            reason = _engine_unavailable_reason(engine)
            if reason:
                unavailable_reasons[engine.name] = reason
            trace.add_stage(StageMetric(stage="engine", engine=engine.name, status="skipped", error=reason[:500]))
            continue
        attempted.append(engine.name)
        try:
            with trace_stage(trace, "engine", engine.name) as metric:
                result = retry_with_backoff(
                    lambda _e=engine: _extract_engine_with_timeout(_e, file_path),
                    max_retries=2,
                    label=f"ocr:{engine.name}",
                )
                _populate_trace_metric(metric, result)
        except Exception as exc:
            error_code = OcrErrorCode.classify(exc)
            failures[engine.name] = f"[{error_code.value}] {exc}"
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
                "ocr_trace": _finish_ocr_trace(trace, selected_engine=result.engine, result=result),
                **result.metadata,
            }
        _record_insufficient_result(engine, result, failures, unavailable_reasons)
        # Track best partial result for graceful degradation
        if result.blocks:
            score = (result.char_count, result.avg_confidence)
            if score > best_partial_score:
                best_partial = (result, engine.name)
                best_partial_score = score

    # Graceful degradation: return best partial result instead of empty
    if best_partial is not None:
        partial_result, partial_engine = best_partial
        blocks = _blocks_from_intelligent_result(partial_result, aliases, document_profile=document_profile)
        return blocks, {
            "ocr_adapter": "intelligent_document",
            "ocr_engine": partial_result.engine,
            "ocr_intelligent_status": "degraded",
            "ocr_degradation_reason": failures.get(partial_engine, "below quality threshold"),
            "ocr_attempted_engines": attempted,
            "ocr_unavailable_engines": unavailable,
            "ocr_unavailable_reasons": unavailable_reasons,
            "ocr_engine_errors": failures,
            "ocr_block_count": len(blocks),
            "ocr_char_count": partial_result.char_count,
            "ocr_avg_confidence": partial_result.avg_confidence,
            "ocr_engine_candidates": candidates,
            "ocr_trace": _finish_ocr_trace(
                trace,
                selected_engine=partial_result.engine,
                result=partial_result,
                error=failures.get(partial_engine, "below quality threshold"),
            ),
            **partial_result.metadata,
        }

    return [], {
        "ocr_adapter": "intelligent_document",
        "ocr_engine": "none",
        "ocr_intelligent_status": "no_engine_result",
        "ocr_attempted_engines": attempted,
        "ocr_unavailable_engines": unavailable,
        "ocr_unavailable_reasons": unavailable_reasons,
        "ocr_engine_errors": failures,
        "ocr_engine_candidates": candidates,
        "ocr_trace": _finish_ocr_trace(trace, error="no_engine_result"),
    }



def default_intelligent_ocr_engines(
    page_kind: str = "image_ocr",
    *,
    document_profile: DocumentProfile | None = None,
) -> list[IntelligentOcrEngine]:
    # Lazy imports to avoid circular dependencies
    from app.services.ocr_engine.engines import (
        HttpDocumentIntelligenceEngine, OpenAIDocumentVisionEngine,
        PaddleOcrHybridPipelineEngine, RemotePaddleOCRVLEngine,
        PPOCRV5OnnxDirectMLEngine, PPOCRV5PaddleEngine,
        PaddleOCRVLEngine, PaddleStructureV3Engine, DoclingEngine,
    )
    profile_id = document_profile.profile_id if document_profile else settings.document_profile
    registry: dict[str, IntelligentOcrEngine] = {
        "document_ai_http": HttpDocumentIntelligenceEngine(profile_id=profile_id),
        "openai_document_vision": OpenAIDocumentVisionEngine(document_prompt=document_ai_prompt(document_profile)),
        "paddleocr_hybrid": PaddleOcrHybridPipelineEngine(),
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


# ---------------------------------------------------------------------------
# Profile / routing helpers
# ---------------------------------------------------------------------------

def _engine_names_for_page_kind(page_kind: str) -> list[str]:
    try:
        profile = load_ocr_profile(settings.ocr_profile)
    except Exception:
        return _with_document_sidecar_if_configured(
            ["pp_ocr_v5_paddle", "paddle_structure_v3", "docling", "paddleocr_vl"], page_kind)
    for rule in profile.page_router:
        if page_kind in rule.page_kinds:
            return _with_document_sidecar_if_configured(
                [name for name in rule.engines if name != "pdf_text"], page_kind)
    enabled = [e for e in profile.engines if e.enabled]
    return _with_document_sidecar_if_configured(
        [e.engine_id for e in sorted(enabled, key=lambda i: i.priority)], page_kind)


def _with_document_sidecar_if_configured(names: list[str], page_kind: str) -> list[str]:
    if page_kind in {"native_pdf_text", "text"}: return names
    if not settings.ocr_document_ai_url: return names
    if "document_ai_http" in names or "paddleocr_vl_remote" in names: return names
    return ["document_ai_http"]


def ocr_engine_options(engine_id: str) -> dict[str, Any]:
    try:
        profile = load_ocr_profile(settings.ocr_profile)
    except Exception:
        return {}
    engine = profile.engine_config(engine_id)
    if engine: return dict(engine.options)
    for stage_config in profile.stage_models.values():
        if isinstance(stage_config, dict) and stage_config.get("engine_id") == engine_id:
            options = stage_config.get("options")
            return dict(options) if isinstance(options, dict) else {}
    return {}


def ocr_stage_config(profile: OcrProfile, stage_name: str) -> dict[str, Any]:
    value = profile.stage_models.get(stage_name, {})
    return dict(value) if isinstance(value, dict) else {}


def active_ocr_profile() -> OcrProfile | None:
    try: return load_ocr_profile(settings.ocr_profile)
    except Exception: return None


def current_accelerator() -> str:
    try: return resolve_ocr_device_status().resolved
    except Exception: return settings.ocr_accelerator or "cpu"


def engine_metadata(model_name: str, model_version: str | None = None, *, accelerator: str | None = None) -> dict:
    return {
        "model_name": model_name, "model_version": model_version,
        "accelerator": accelerator or current_accelerator(),
        "engine_version": f"{model_name}:{model_version or 'default'}",
        "route_profile_id": settings.ocr_profile,
    }


def preload_torch_for_windows() -> None:
    import os
    if os.name != "nt": return
    spec = importlib.util.find_spec("torch")
    if spec is None or spec.origin is None: return
    try:
        # Pre-add torch/lib directory to DLL search path to avoid [WinError 127] on shm.dll
        torch_dir = os.path.dirname(spec.origin)
        torch_lib = os.path.join(torch_dir, "lib")
        if os.path.isdir(torch_lib):
            try:
                os.add_dll_directory(torch_lib)
            except Exception:
                pass
        import torch  # noqa: F401
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("preload_torch_for_windows failed: %s", e, exc_info=True)
        return


def paddleocr_package_available() -> bool:
    return importlib.util.find_spec("paddleocr") is not None


def import_paddle_ocr_class():
    from paddleocr import PaddleOCR
    return PaddleOCR


# ---------------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------------

def _result_is_sufficient(result: IntelligentOcrResult) -> bool:
    if not result.blocks: return False
    has_structured = any(b.block_type in {"table", "cell", "form_field", "key_value"} for b in result.blocks)
    if has_structured and result.char_count > 0: return True
    min_chars = max(1, int(settings.ocr_intelligent_min_chars))
    if result.char_count < min_chars: return False
    return result.avg_confidence >= settings.ocr_intelligent_min_confidence


def _engine_unavailable_reason(engine: IntelligentOcrEngine) -> str:
    method = getattr(engine, "unavailable_reason", None)
    if not callable(method): return ""
    try: return str(method())
    except Exception: return ""


def _extract_engine_with_timeout(engine: IntelligentOcrEngine, file_path: Path) -> IntelligentOcrResult:
    timeout_seconds = _engine_timeout_seconds(engine.name)
    if timeout_seconds <= 0:
        return engine.extract(file_path)
    try:
        return run_with_timeout(lambda path: engine.extract(path), file_path, timeout=timeout_seconds)
    except TimeoutError as exc:
        raise OcrEngineError(
            OcrErrorCode.PAGE_TIMEOUT,
            f"engine exceeded timeout of {timeout_seconds}s",
            engine_name=engine.name,
            stage="engine",
            recoverable=True,
        ) from exc


def _engine_timeout_seconds(engine_name: str) -> float:
    options = ocr_engine_options(engine_name)
    for key in ("timeout_seconds", "document_timeout_seconds", "page_timeout_seconds"):
        value = options.get(key)
        if value is None:
            continue
        try:
            parsed = float(value)
        except Exception:
            continue
        if parsed > 0:
            return parsed
    try:
        return max(0.0, float(settings.ocr_engine_timeout_seconds))
    except Exception:
        return 120.0


def _start_ocr_trace(file_path: Path) -> OcrTrace:
    try:
        file_size = file_path.stat().st_size
    except Exception:
        file_size = 0
    trace = OcrTrace(
        trace_id=hashlib.sha1(f"{file_path}:{time.time_ns()}".encode("utf-8")).hexdigest()[:12],
        file_name=file_path.name,
        file_size=file_size,
    )
    trace.start()
    return trace


def _populate_trace_metric(metric: StageMetric, result: IntelligentOcrResult) -> None:
    metric.block_count = len(result.blocks)
    metric.char_count = result.char_count
    metric.avg_confidence = result.avg_confidence
    pages = sorted({block.page for block in result.blocks if block.page >= 1})
    metric.page_metrics = [page_quality_metrics(result.blocks, page) for page in pages]


def _finish_ocr_trace(
    trace: OcrTrace,
    *,
    selected_engine: str = "",
    result: IntelligentOcrResult | None = None,
    error: str = "",
) -> dict[str, Any]:
    trace.selected_engine = selected_engine
    if result is not None:
        trace.result_block_count = len(result.blocks)
        trace.result_char_count = result.char_count
        trace.result_avg_confidence = result.avg_confidence
        trace.quality_band = quality_band(result.avg_confidence)
        trace.page_count = len({block.page for block in result.blocks if block.page >= 1})
    if error:
        trace.error = error[:500]
    trace.finish()
    return trace.to_dict()


def _record_insufficient_result(engine, result, failures, unavailable_reasons):
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
        failures.setdefault(engine.name,
            f"engine result below quality threshold: chars={result.char_count}, confidence={result.avg_confidence:.3f}")


def _candidate_summary(engine_name: str, result: IntelligentOcrResult, *, sufficient: bool) -> dict:
    structured_count = len([b for b in result.blocks
        if b.block_type in {"table", "cell", "form_field", "key_value", "checkbox", "selection_mark"}])
    return {
        "engine": result.engine or engine_name, "route_engine": engine_name,
        "sufficient": sufficient, "block_count": len(result.blocks),
        "char_count": result.char_count, "avg_confidence": round(result.avg_confidence, 4),
        "structured_block_count": structured_count,
        "quality_band": "good" if result.avg_confidence >= 0.9 else "fair" if result.avg_confidence >= 0.75 else "poor",
        "alternative_blocks": [
            {"page": b.page, "text": b.text, "bbox": b.bbox, "confidence": b.confidence,
             "block_type": b.block_type, "table_id": b.table_id, "row": b.row, "col": b.col,
             "row_span": b.row_span, "col_span": b.col_span}
            for b in result.blocks[:5]
        ],
    }


def _blocks_from_intelligent_result(result, aliases, *, document_profile=None) -> list[DocumentIRBlock]:
    blocks = []
    current_section = "未知"
    for reading_order, source in enumerate(result.blocks, start=1):
        section = _detect_section(source.text, aliases) or current_section
        current_section = section
        blocks.append(DocumentIRBlock(
            block_id=_block_id(reading_order, result.engine, source),
            page=max(1, source.page), reading_order=reading_order, text=source.text,
            bbox=source.bbox, confidence=max(0.0, min(1.0, source.confidence)),
            block_type=_normalize_block_type(source.block_type),
            section_id=_section_id(section), section_label=section,
            document_kind=document_kind_for_section(section, document_profile),
            table_id=source.table_id, row=source.row, col=source.col,
            row_span=max(1, source.row_span), col_span=max(1, source.col_span),
            model_name=source.model_name or _opt_str(result.metadata, "model_name"),
            model_version=source.model_version or _opt_str(result.metadata, "model_version"),
            accelerator=_opt_str(result.metadata, "accelerator"),
            engine_version=_opt_str(result.metadata, "engine_version"),
            route_profile_id=_opt_str(result.metadata, "route_profile_id") or settings.ocr_profile,
            stage_source=source.stage_source or _opt_str(result.metadata, "stage_source"),
            model_variant=source.model_variant or _opt_str(result.metadata, "model_variant"),
            render_dpi=source.render_dpi or _opt_int(result.metadata, "render_dpi"),
            preprocess_profile=source.preprocess_profile or _opt_str(result.metadata, "preprocess_profile"),
            candidate_id=source.candidate_id, candidate_group_id=source.candidate_group_id,
            conflict_flags=list(source.conflict_flags), canonical_source_ids=list(source.canonical_source_ids),
            layout_region_id=source.layout_region_id, line_group_id=source.line_group_id,
            coordinate_system=source.coordinate_system, merge_confidence=source.merge_confidence,
            merge_flags=list(source.merge_flags),
        ))
    return blocks


def _opt_str(metadata: dict, key: str) -> str | None:
    value = metadata.get(key)
    return str(value) if value is not None and str(value).strip() else None


def _opt_int(metadata: dict, key: str) -> int | None:
    value = metadata.get(key)
    try: return int(value) if value is not None else None
    except Exception: return None


def _normalize_block_type(block_type: str) -> str:
    if block_type in {"line", "paragraph", "table", "title", "text", "form_field",
                       "cell", "checkbox", "selection_mark", "key_value"}:
        return block_type
    return "text"


def _block_id(reading_order: int, engine: str, block: IntelligentOcrBlock) -> str:
    digest = hashlib.sha1(
        f"{engine}:{block.page}:{block.block_type}:{block.text}:{block.row}:{block.col}:{block.row_span}:{block.col_span}".encode("utf-8")
    ).hexdigest()
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
            if found in names: return label
    return None


def _section_id(label: str) -> str:
    return hashlib.sha1(label.encode("utf-8")).hexdigest()[:12]


# Backward-compatible aliases
_ocr_engine_options = ocr_engine_options
_ocr_stage_config = ocr_stage_config
_active_ocr_profile = active_ocr_profile
_engine_metadata = engine_metadata
_current_accelerator = current_accelerator
_preload_torch_for_windows = preload_torch_for_windows
_paddleocr_package_available = paddleocr_package_available
_import_paddle_ocr_class = import_paddle_ocr_class
_optional_metadata_str = _opt_str
_optional_metadata_int = _opt_int
