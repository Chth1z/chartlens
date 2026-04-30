from __future__ import annotations

import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from fastapi import FastAPI, File, Form, UploadFile

from app.services.intelligent_ocr import (
    DoclingEngine,
    IntelligentOcrEngine,
    IntelligentOcrResult,
    PPOCRV5OnnxDirectMLEngine,
    PPOCRV5PaddleEngine,
    PaddleOCRVLEngine,
    PaddleStructureV3Engine,
    _engine_names_for_page_kind,
)
from app.core.config_loader import load_ocr_profile
from app.core.settings import settings
from app.services.ocr_accelerators import accelerator_probe, resolve_ocr_device_status

app = FastAPI(title="EYEX OCR Sidecar", version="1.0.0")


@app.get("/health")
def health() -> dict:
    engines = local_engines()
    profile = _active_ocr_profile_payload()
    return {
        "ok": True,
        "ocr_profile": profile,
        "device": paddle_device_status(),
        "available_accelerators": accelerator_probe(),
        "engines": [engine_status(engine) for engine in engines],
    }


@app.post("/extract")
async def extract(file: UploadFile = File(...), profile_id: str = Form("medical_inpatient_zh")) -> dict:
    suffix = Path(file.filename or "document.pdf").suffix or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)
    try:
        payload = extract_with_engines(tmp_path, local_engines())
        payload["profile_id"] = profile_id
        return payload
    finally:
        tmp_path.unlink(missing_ok=True)


def local_engines(page_kind: str = "image_ocr") -> list[IntelligentOcrEngine]:
    registry: dict[str, IntelligentOcrEngine] = {
        "pp_ocr_v5_onnx_directml": PPOCRV5OnnxDirectMLEngine(),
        "pp_ocr_v5_paddle": PPOCRV5PaddleEngine(),
        "paddleocr_vl": PaddleOCRVLEngine(),
        "paddle_structure_v3": PaddleStructureV3Engine(),
        "docling": DoclingEngine(),
    }
    configured = os.getenv("EYEX_OCR_SIDECAR_ENGINES", "").strip()
    names = [item.strip() for item in configured.split(",") if item.strip()] if configured else _engine_names_for_page_kind(page_kind)
    return [registry[name] for name in names if name in registry]


def engine_status(engine: IntelligentOcrEngine) -> dict:
    available = engine.available()
    return {
        "name": engine.name,
        "available": available,
        "unavailable_reason": "" if available else _unavailable_reason(engine),
    }


def extract_with_engines(file_path: Path, engines: Iterable[IntelligentOcrEngine]) -> dict:
    device_error = configure_paddle_device()
    if device_error:
        return {
            "engine": "none",
            "blocks": [],
            "attempted_engines": [],
            "unavailable_engines": [],
            "unavailable_reasons": {},
            "engine_errors": {"paddle_device": device_error},
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
            continue
        attempted.append(engine.name)
        try:
            result = engine.extract(file_path)
        except Exception as exc:
            errors[engine.name] = str(exc)
            continue
        if result.blocks:
            return _payload_from_result(result, attempted, unavailable, unavailable_reasons, errors)

    return {
        "engine": "none",
        "blocks": [],
        "attempted_engines": attempted,
        "unavailable_engines": unavailable,
        "unavailable_reasons": unavailable_reasons,
        "engine_errors": errors,
    }


def _payload_from_result(
    result: IntelligentOcrResult,
    attempted: list[str],
    unavailable: list[str],
    unavailable_reasons: dict[str, str],
    errors: dict[str, str],
) -> dict:
    return {
        "engine": result.engine,
        "blocks": [asdict(block) for block in result.blocks],
        "attempted_engines": attempted,
        "unavailable_engines": unavailable,
        "unavailable_reasons": unavailable_reasons,
        "engine_errors": errors,
        "metadata": result.metadata,
    }


def _unavailable_reason(engine: IntelligentOcrEngine) -> str:
    reason = getattr(engine, "unavailable_reason", None)
    return str(reason()) if callable(reason) else ""


def configure_paddle_device() -> str:
    accelerator = os.getenv("EYEX_OCR_ACCELERATOR", os.getenv("EYEX_OCR_DEVICE", "auto")).strip().lower()
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
            return "EYEX_OCR_DEVICE=gpu but installed PaddlePaddle is not compiled with CUDA"
        if accelerator == "rocm" and not compiled_rocm:
            return "EYEX_OCR_ACCELERATOR=rocm but installed PaddlePaddle is not compiled with ROCm"
        paddle.set_device(device)
        return ""
    except Exception as exc:
        return str(exc)


def paddle_device_status() -> dict:
    status = resolve_ocr_device_status().model_dump()
    status["requested"] = os.getenv("EYEX_OCR_ACCELERATOR", os.getenv("EYEX_OCR_DEVICE", status.get("requested", "auto")))
    return status


def _active_ocr_profile_payload() -> dict:
    try:
        return load_ocr_profile(settings.ocr_profile).model_dump()
    except Exception as exc:
        return {"profile_id": settings.ocr_profile, "label": settings.ocr_profile, "load_error": str(exc)}


def preload_torch_for_windows() -> None:
    if os.name != "nt":
        return
    try:
        import torch  # noqa: F401
    except Exception:
        pass
