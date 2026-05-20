from __future__ import annotations

import importlib.util
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.core.settings import settings
from app.domain.models import OcrDeviceStatus


def accelerator_probe() -> dict[str, dict[str, Any]]:
    return {
        "directml": _directml_probe(),
        "cuda": _cuda_probe(),
        "rocm": _rocm_probe(),
        "remote": _remote_probe(),
        "wsl": _command_probe("wsl"),
        "docker": _command_probe("docker"),
    }


def resolve_ocr_device_status() -> OcrDeviceStatus:
    requested = settings.ocr_accelerator or "auto"
    probes = accelerator_probe()
    resolved = _resolve_requested_accelerator(requested, probes)
    paddle = _paddle_probe()
    available = [name for name, probe in probes.items() if probe.get("available")]
    return OcrDeviceStatus(
        requested=requested,
        resolved=resolved,
        accelerator=resolved,
        compiled_cuda=bool(paddle.get("compiled_cuda")),
        compiled_rocm=bool(paddle.get("compiled_rocm")),
        current=str(paddle.get("current") or resolved),
        available_accelerators=available,
        probes={**probes, "paddle": paddle},
    )


def _resolve_requested_accelerator(requested: str, probes: dict[str, dict[str, Any]]) -> str:
    normalized = requested.lower()
    if normalized in {"cpu", "cuda", "rocm", "directml", "remote"}:
        return normalized if probes.get(normalized, {}).get("available", normalized == "cpu") else "cpu"
    if probes.get("directml", {}).get("available"):
        return "directml"
    if probes.get("cuda", {}).get("available"):
        return "cuda"
    if probes.get("rocm", {}).get("available"):
        return "rocm"
    if probes.get("remote", {}).get("available"):
        return "remote"
    return "cpu"


def _directml_probe() -> dict[str, Any]:
    providers = _onnx_available_providers()
    model_dir = settings.ocr_directml_model_dir
    runtime_disabled_reason = _directml_runtime_disabled_reason()
    model_ready = _directml_model_dir_ready(model_dir)
    return {
        "available": "DmlExecutionProvider" in providers and model_ready and not runtime_disabled_reason,
        "provider_available": "DmlExecutionProvider" in providers,
        "providers": providers,
        "model_dir": str(model_dir) if model_dir else "",
        "model_dir_exists": model_ready,
        "runtime_disabled": bool(runtime_disabled_reason),
        "runtime_disabled_reason": runtime_disabled_reason,
    }


def _directml_model_dir_ready(model_dir: Path | None) -> bool:
    if not model_dir:
        return False
    path = Path(model_dir)
    return (
        path.exists()
        and (path / "ch_PP-OCRv5_det_server.onnx").exists()
        and (path / "ch_PP-OCRv5_rec_server.onnx").exists()
    )


def _directml_runtime_disabled_reason() -> str:
    try:
        from app.services.ocr_engine.errors import directml_disabled_reason

        return str(directml_disabled_reason() or "")
    except Exception:
        return ""


def _onnx_available_providers() -> list[str]:
    if importlib.util.find_spec("onnxruntime") is None:
        return []
    try:
        import onnxruntime as ort

        return [str(provider) for provider in ort.get_available_providers()]
    except Exception:
        return []


def _cuda_probe() -> dict[str, Any]:
    paddle = _paddle_probe()
    return {
        "available": bool(paddle.get("compiled_cuda")),
        "compiled_cuda": bool(paddle.get("compiled_cuda")),
        "nvidia_smi": bool(shutil.which("nvidia-smi")),
    }


def _rocm_probe() -> dict[str, Any]:
    paddle = _paddle_probe()
    commands = {
        "rocminfo": bool(shutil.which("rocminfo")),
        "rocm-smi": bool(shutil.which("rocm-smi")),
        "hipcc": bool(shutil.which("hipcc")),
    }
    return {
        "available": bool(paddle.get("compiled_rocm")) or any(commands.values()),
        "compiled_rocm": bool(paddle.get("compiled_rocm")),
        "commands": commands,
        "note": "RX 6600 is not enabled by default; use a validated ROCm sidecar for PaddleOCR-VL.",
    }


def _remote_probe() -> dict[str, Any]:
    url = settings.ocr_paddleocr_vl_url or ""
    return {
        "available": bool(url),
        "url": url,
        "purpose": "paddleocr_vl_remote",
    }


def _command_probe(command: str) -> dict[str, Any]:
    path = shutil.which(command)
    return {"available": bool(path), "path": path or ""}


def _paddle_probe() -> dict[str, Any]:
    if importlib.util.find_spec("paddle") is None:
        return {"available": False, "current": "unavailable", "compiled_cuda": False, "compiled_rocm": False}
    try:
        import paddle

        rocm_check = getattr(paddle, "is_compiled_with_rocm", None)
        return {
            "available": True,
            "current": str(paddle.get_device()),
            "compiled_cuda": bool(paddle.is_compiled_with_cuda()),
            "compiled_rocm": bool(rocm_check()) if callable(rocm_check) else False,
            "version": str(getattr(paddle, "__version__", "")),
        }
    except Exception as exc:
        return {
            "available": False,
            "current": "unavailable",
            "compiled_cuda": False,
            "compiled_rocm": False,
            "error": str(exc),
        }
