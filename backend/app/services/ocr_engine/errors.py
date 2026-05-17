"""Structured OCR error codes — replaces ad-hoc string error propagation.

Mature OCR pipelines (Surya, MinerU, Docling) use structured error categories
for retry logic, monitoring, and operator diagnostics. This module classifies
OCR failures into actionable categories.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class OcrErrorCode(str, Enum):
    """Structured error codes for OCR pipeline failures."""

    ENGINE_UNAVAILABLE = "ENGINE_UNAVAILABLE"
    DIRECTML_CRASH = "DIRECTML_CRASH"
    DIRECTML_TIMEOUT = "DIRECTML_TIMEOUT"
    TIMEOUT = "TIMEOUT"
    INSUFFICIENT_RESULT = "INSUFFICIENT_RESULT"
    INPUT_INVALID = "INPUT_INVALID"
    MEMORY_EXHAUSTED = "MEMORY_EXHAUSTED"
    MODEL_LOAD_FAILED = "MODEL_LOAD_FAILED"
    NETWORK_ERROR = "NETWORK_ERROR"
    SIDECAR_UNAVAILABLE = "SIDECAR_UNAVAILABLE"
    STAGE_FAILED = "STAGE_FAILED"
    PAGE_TIMEOUT = "PAGE_TIMEOUT"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"

    @classmethod
    def classify(cls, exc: Exception) -> "OcrErrorCode":
        """Classify an exception into a structured error code."""
        if isinstance(exc, OcrEngineError):
            return exc.code
        message = str(exc).lower()

        # DirectML-specific failures
        if any(term in message for term in ("dxgi_error", "device_removed", "directml", "dml")):
            return cls.DIRECTML_CRASH

        # Memory failures
        if any(term in message for term in ("out of memory", "oom", "memory", "alloc")):
            return cls.MEMORY_EXHAUSTED

        # Timeout
        if any(term in message for term in ("timeout", "timed out", "deadline")):
            return cls.TIMEOUT

        # Network/HTTP
        if any(term in message for term in ("connection", "httpx", "connect", "refused", "unreachable")):
            return cls.NETWORK_ERROR

        # Model loading
        if any(term in message for term in ("model", "load", "onnx", "weight", "checkpoint")):
            return cls.MODEL_LOAD_FAILED

        # Input validation
        if any(term in message for term in ("invalid", "corrupt", "format", "unsupported")):
            return cls.INPUT_INVALID

        return cls.UNKNOWN_ERROR


class OcrEngineError(Exception):
    """Structured OCR engine error with error code and context metadata."""

    def __init__(
        self,
        code: OcrErrorCode,
        message: str,
        *,
        engine_name: str = "",
        stage: str = "",
        page: int | None = None,
        recoverable: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.engine_name = engine_name
        self.stage = stage
        self.page = page
        self.recoverable = recoverable
        self.metadata = metadata or {}
        super().__init__(f"[{code.value}] {engine_name}: {message}")

    def to_dict(self) -> dict[str, Any]:
        """Serialize for diagnostics/logging."""
        return {
            "error_code": self.code.value,
            "engine_name": self.engine_name,
            "stage": self.stage,
            "page": self.page,
            "recoverable": self.recoverable,
            "message": str(self),
            **self.metadata,
        }


# ---------------------------------------------------------------------------
# DirectML auto-recovery state — replaces permanent per-process disable
# ---------------------------------------------------------------------------

_DIRECTML_FAILURE_COUNT: int = 0
_DIRECTML_MAX_RETRIES: int = 3
_DIRECTML_COOLDOWN_UNTIL: float = 0.0
_DIRECTML_COOLDOWN_SECONDS: float = 120.0
_DIRECTML_RUNTIME_DISABLED_REASON: str | None = None


def directml_disabled_reason() -> str | None:
    """Return the current DirectML disable reason, or None if available."""
    import time

    global _DIRECTML_RUNTIME_DISABLED_REASON, _DIRECTML_FAILURE_COUNT
    if _DIRECTML_RUNTIME_DISABLED_REASON is None:
        return None
    # Auto-recovery: if cooldown has elapsed and retries remain, clear the disable
    if _DIRECTML_FAILURE_COUNT < _DIRECTML_MAX_RETRIES and time.time() >= _DIRECTML_COOLDOWN_UNTIL:
        _DIRECTML_RUNTIME_DISABLED_REASON = None
        return None
    return _DIRECTML_RUNTIME_DISABLED_REASON


def disable_directml_for_process(exc: Exception) -> None:
    """Mark DirectML as disabled with auto-recovery after cooldown."""
    import time

    global _DIRECTML_RUNTIME_DISABLED_REASON, _DIRECTML_FAILURE_COUNT, _DIRECTML_COOLDOWN_UNTIL
    _DIRECTML_FAILURE_COUNT += 1
    _DIRECTML_COOLDOWN_UNTIL = time.time() + _DIRECTML_COOLDOWN_SECONDS
    message = str(exc).strip() or exc.__class__.__name__
    if _DIRECTML_FAILURE_COUNT >= _DIRECTML_MAX_RETRIES:
        _DIRECTML_RUNTIME_DISABLED_REASON = (
            f"DirectML permanently disabled after {_DIRECTML_FAILURE_COUNT} failures; "
            f"restart the sidecar to retry GPU. Last error: {message[:400]}"
        )
    else:
        _DIRECTML_RUNTIME_DISABLED_REASON = (
            f"DirectML disabled for this OCR sidecar process after runtime failure "
            f"(attempt {_DIRECTML_FAILURE_COUNT}/{_DIRECTML_MAX_RETRIES}, "
            f"auto-retry in {_DIRECTML_COOLDOWN_SECONDS:.0f}s); "
            f"Last error: {message[:400]}"
        )


def reset_directml_state() -> None:
    """Reset DirectML state — for testing only."""
    global _DIRECTML_RUNTIME_DISABLED_REASON, _DIRECTML_FAILURE_COUNT, _DIRECTML_COOLDOWN_UNTIL
    _DIRECTML_RUNTIME_DISABLED_REASON = None
    _DIRECTML_FAILURE_COUNT = 0
    _DIRECTML_COOLDOWN_UNTIL = 0.0
