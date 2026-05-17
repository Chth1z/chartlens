from __future__ import annotations

import hashlib
import os
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

# FIX: Import torch before any paddle imports to prevent DLL conflicts.
# If paddle is imported first, it loads vendored DLLs (like OpenMP) that conflict
# with torch's DLLs, causing WinError 127 when torch tries to load shm.dll.
try:
    import torch  # noqa: F401
except ImportError:
    pass

from typing import Iterable

from fastapi import FastAPI, File, Form, UploadFile
from starlette.concurrency import run_in_threadpool

from app.services.ocr_engine.concurrency import run_with_timeout
from app.services.ocr_engine.engine_base import IntelligentOcrEngine, _engine_names_for_page_kind
from app.services.ocr_engine.errors import OcrErrorCode, OcrEngineError
from app.services.ocr_engine.observability import OcrTrace, StageMetric, page_quality_metrics, quality_band, trace_stage
from app.services.ocr_engine.types import IntelligentOcrResult
from app.services.ocr_engine.engines import (
    DoclingEngine,
    PPOCRV5OnnxDirectMLEngine,
    PPOCRV5PaddleEngine,
    PaddleOcrHybridPipelineEngine,
    PaddleOCRVLEngine,
    PaddleStructureV3Engine,
    RemotePaddleOCRVLEngine,
)
from app.core.config_loader import load_ocr_profile
from app.core.settings import settings
from app.services.ocr_accelerators import accelerator_probe, resolve_ocr_device_status

SIDECAR_API_CONTRACT_VERSION = "eyex-ocr-sidecar-v2"
SIDECAR_BUILD_ID = "ocr-sidecar-2026-05-06-layout-metrics-stale-detect"
SIDECAR_RESTART_MESSAGE = "Restart OCR sidecar with .\\start.cmd so the running process loads the current EYEX OCR code."

app = FastAPI(title="EYEX OCR Sidecar", version="1.0.0")


@app.get("/health")
def health() -> dict:
    engines = local_engines()
    profile = _active_ocr_profile_payload()
    return {
        "ok": True,
        "api_contract_version": SIDECAR_API_CONTRACT_VERSION,
        "sidecar_build_id": SIDECAR_BUILD_ID,
        "restart_message": SIDECAR_RESTART_MESSAGE,
        "ocr_profile": profile,
        "pipeline_stages": profile.get("pipeline_stages", []),
        "stage_models": profile.get("stage_models", {}),
        "strong_pipeline_readiness": _strong_pipeline_readiness(profile),
        "memory_protection": {
            "page_processing": "serial",
            "local_cpu_paddleocr_vl_autoload": False,
            "cache_root_project_local": True,
        },
        "cache_root": str(_sidecar_cache_root()),
        "device": paddle_device_status(),
        "available_accelerators": accelerator_probe(),
        "engines": [engine_status(engine) for engine in engines],
    }


@app.post("/extract")
async def extract(file: UploadFile = File(...), profile_id: str = Form("medical_inpatient_zh")) -> dict:
    suffix = Path(file.filename or "document.pdf").suffix or ".pdf"
    tmp_root = _sidecar_cache_root() / "tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=str(tmp_root)) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)
    try:
        payload = await run_in_threadpool(extract_with_engines, tmp_path, local_engines())
        payload["profile_id"] = profile_id
        return payload
    finally:
        tmp_path.unlink(missing_ok=True)


def local_engines(page_kind: str = "image_ocr") -> list[IntelligentOcrEngine]:
    registry = _sidecar_engine_registry()
    names = _engine_names_for_page_kind(page_kind)
    names = [name for name in names if name != "document_ai_http"]
    if not names:
        names = _sidecar_profile_engine_names(page_kind)
    return [registry[name] for name in names if name in registry]


# Module-level engine registry — instantiated once per sidecar process.
# PPStructureV3/PaddleX does NOT support re-initialization; a fresh registry
# on every /health call caused "PDX has already been initialized" crashes.
_ENGINE_REGISTRY: dict[str, IntelligentOcrEngine] | None = None


def _sidecar_engine_registry() -> dict[str, IntelligentOcrEngine]:
    global _ENGINE_REGISTRY
    if _ENGINE_REGISTRY is None:
        _ENGINE_REGISTRY = {
            "paddleocr_hybrid": PaddleOcrHybridPipelineEngine(),
            "pp_ocr_v5_onnx_directml": PPOCRV5OnnxDirectMLEngine(),
            "pp_ocr_v5_paddle": PPOCRV5PaddleEngine(),
            "paddleocr_vl": PaddleOCRVLEngine(),
            "paddleocr_vl_remote": RemotePaddleOCRVLEngine(),
            "paddle_structure_v3": PaddleStructureV3Engine(),
            "docling": DoclingEngine(),
        }
    return _ENGINE_REGISTRY



def _sidecar_profile_engine_names(page_kind: str) -> list[str]:
    try:
        profile = load_ocr_profile(settings.ocr_profile)
    except Exception:
        return ["paddleocr_hybrid"]
    for rule in profile.page_router:
        if page_kind in rule.page_kinds:
            return [name for name in rule.engines if name != "pdf_text"]
    return [engine.engine_id for engine in sorted(profile.engines, key=lambda item: item.priority) if engine.enabled]


def engine_status(engine: IntelligentOcrEngine) -> dict:
    available = engine.available()
    return {
        "name": engine.name,
        "available": available,
        "unavailable_reason": "" if available else _unavailable_reason(engine),
    }


def _strong_pipeline_readiness(profile: dict) -> dict:
    stage_models = profile.get("stage_models", {})
    gpu_policy = profile.get("gpu_policy", {})
    required_stages = gpu_policy.get("strong_pipeline_requires") or [
        stage
        for stage, config in stage_models.items()
        if isinstance(config, dict) and config.get("enabled", True) is not False and config.get("required", True) is not False
    ]
    registry = _sidecar_engine_registry()
    stages = {}
    ready = True
    for stage in required_stages:
        config = stage_models.get(stage, {}) if isinstance(stage_models, dict) else {}
        engine_id = str(config.get("engine_id") or stage) if isinstance(config, dict) else str(stage)
        engine = registry.get(engine_id)
        if engine is None:
            stages[stage] = {"ready": False, "engine_id": engine_id, "reason": "engine not registered"}
            ready = False
            continue
        status = engine_status(engine)
        stages[stage] = {
            "ready": bool(status["available"]),
            "engine_id": engine_id,
            "reason": status["unavailable_reason"],
        }
        ready = ready and bool(status["available"])
    return {"ready": ready, "stages": stages}


def extract_with_engines(file_path: Path, engines: Iterable[IntelligentOcrEngine]) -> dict:
    device_error = configure_paddle_device()
    trace = _start_ocr_trace(file_path)
    if device_error:
        return {
            "engine": "none",
            "blocks": [],
            "attempted_engines": [],
            "unavailable_engines": [],
            "unavailable_reasons": {},
            "engine_errors": {"paddle_device": device_error},
            "metadata": {"ocr_trace": _finish_ocr_trace(trace, error=device_error)},
        }

    attempted: list[str] = []
    unavailable: list[str] = []
    unavailable_reasons: dict[str, str] = {}
    errors: dict[str, str] = {}

    for engine in engines:
        if not engine.available():
            unavailable.append(engine.name)
            reason = _unavailable_reason(engine)
            if reason:
                unavailable_reasons[engine.name] = reason
            trace.add_stage(StageMetric(stage="engine", engine=engine.name, status="skipped", error=reason[:500]))
            continue
        attempted.append(engine.name)
        try:
            with trace_stage(trace, "engine", engine.name) as metric:
                result = _extract_engine_with_timeout(engine, file_path)
                _populate_trace_metric(metric, result)
        except Exception as exc:
            error_code = OcrErrorCode.classify(exc)
            errors[engine.name] = f"[{error_code.value}] {exc}"
            continue
        if result.blocks:
            return _payload_from_result(
                result,
                attempted,
                unavailable,
                unavailable_reasons,
                errors,
                trace=_finish_ocr_trace(trace, selected_engine=result.engine, result=result),
            )

    return {
        "engine": "none",
        "blocks": [],
        "attempted_engines": attempted,
        "unavailable_engines": unavailable,
        "unavailable_reasons": unavailable_reasons,
        "engine_errors": errors,
        "metadata": {"ocr_trace": _finish_ocr_trace(trace, error="no_engine_result")},
    }


def _payload_from_result(
    result: IntelligentOcrResult,
    attempted: list[str],
    unavailable: list[str],
    unavailable_reasons: dict[str, str],
    errors: dict[str, str],
    *,
    trace: dict[str, object],
) -> dict:
    metadata = {**result.metadata, "ocr_trace": trace}
    return {
        "engine": result.engine,
        "blocks": [asdict(block) for block in result.blocks],
        "pages": metadata.get("pages", []),
        "tables": metadata.get("tables", []),
        "cells": metadata.get("cells", []),
        "raw_markdown": metadata.get("raw_markdown"),
        "stage_metrics": metadata.get("stage_metrics", {}),
        "candidate_sets": metadata.get("candidate_sets", {}),
        "attempted_engines": attempted,
        "unavailable_engines": unavailable,
        "unavailable_reasons": unavailable_reasons,
        "engine_errors": errors,
        "metadata": metadata,
    }


def _unavailable_reason(engine: IntelligentOcrEngine) -> str:
    reason = getattr(engine, "unavailable_reason", None)
    return str(reason()) if callable(reason) else ""


def configure_paddle_device() -> str:
    accelerator = os.getenv("EYEX_OCR_ACCELERATOR", "auto").strip().lower()
    device = "gpu" if accelerator in {"gpu", "cuda", "rocm"} else accelerator
    if device in {"auto", "directml", "remote"}:
        return ""
    if device not in {"gpu", "cpu"}:
        return ""
    try:
        preload_torch_for_windows()
        import paddle

        rocm_check = getattr(paddle, "is_compiled_with_rocm", None)
        compiled_rocm = bool(rocm_check()) if callable(rocm_check) else False
        if accelerator in {"gpu", "cuda"} and not paddle.is_compiled_with_cuda():
            return "EYEX_OCR_ACCELERATOR=cuda but installed PaddlePaddle is not compiled with CUDA"
        if accelerator == "rocm" and not compiled_rocm:
            return "EYEX_OCR_ACCELERATOR=rocm but installed PaddlePaddle is not compiled with ROCm"
        paddle.set_device(device)
        return ""
    except Exception as exc:
        return str(exc)


def paddle_device_status() -> dict:
    status = resolve_ocr_device_status().model_dump()
    status["requested"] = os.getenv("EYEX_OCR_ACCELERATOR", status.get("requested", "auto"))
    return status


def _active_ocr_profile_payload() -> dict:
    try:
        return load_ocr_profile(settings.ocr_profile).model_dump()
    except Exception as exc:
        return {"profile_id": settings.ocr_profile, "label": settings.ocr_profile, "load_error": str(exc)}


def _sidecar_cache_root() -> Path:
    return settings.storage_dir.parent / "cache" / "ocr-sidecar"


def _extract_engine_with_timeout(engine: IntelligentOcrEngine, file_path: Path) -> IntelligentOcrResult:
    timeout_seconds = _engine_timeout_seconds()
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


def _engine_timeout_seconds() -> float:
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
) -> dict:
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


def preload_torch_for_windows() -> None:
    if os.name != "nt":
        return
    try:
        import torch  # noqa: F401
    except Exception:
        pass
