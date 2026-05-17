"""Confidence calibration — maps raw OCR model scores to calibrated probabilities.

Mature OCR pipelines (Surya, production PaddleOCR) recognize that raw model
confidence scores are often poorly calibrated (overconfident). This module
provides:

1. Temperature scaling — lightweight post-hoc calibration
2. Per-engine calibration profiles
3. Confidence-based quality routing
"""

from __future__ import annotations

import math
from typing import Any


# Default temperature per engine — tuned based on empirical observation.
# T > 1.0 = soften overconfident scores; T < 1.0 = sharpen underconfident scores.
_ENGINE_TEMPERATURES: dict[str, float] = {
    "pp_ocr_v5_onnx_directml": 1.15,   # DirectML tends to be overconfident
    "pp_ocr_v5_paddle": 1.10,           # Paddle native slightly overconfident
    "paddle_structure_v3": 1.05,        # Structure V3 is well-calibrated
    "paddleocr_vl": 1.20,               # VL models are often overconfident
    "paddleocr_hybrid": 1.10,           # Inherited from sub-engines
    "docling": 1.00,                     # Docling assigns conservative scores
    "document_ai_http": 1.00,           # Sidecar — already calibrated internally
    "openai_document_vision": 1.00,     # API-provided scores — leave as-is
}


def calibrate_confidence(
    raw_confidence: float,
    *,
    engine_name: str = "",
    temperature: float | None = None,
) -> float:
    """Apply temperature scaling to calibrate raw OCR confidence.

    Temperature scaling transforms logit-space confidence:
        calibrated = sigmoid(logit / T) where logit = log(p / (1-p))

    Args:
        raw_confidence: Raw model confidence in [0, 1].
        engine_name: Engine identifier for per-engine temperature lookup.
        temperature: Override temperature. If None, uses per-engine default.

    Returns:
        Calibrated confidence in [0, 1].
    """
    # Clamp to valid range
    p = max(1e-6, min(1.0 - 1e-6, raw_confidence))

    # Resolve temperature
    t = temperature if temperature is not None else _ENGINE_TEMPERATURES.get(engine_name, 1.0)

    # No-op for T=1.0
    if abs(t - 1.0) < 1e-6:
        return raw_confidence

    # Convert to logit, scale, convert back
    logit = math.log(p / (1.0 - p))
    scaled_logit = logit / t
    calibrated = 1.0 / (1.0 + math.exp(-scaled_logit))

    return round(max(0.0, min(1.0, calibrated)), 6)


def calibrate_blocks(blocks, *, engine_name: str = "") -> list:
    """Apply calibration to all blocks in a list (in-place-safe for frozen dataclasses).

    Returns new block instances with calibrated confidence.
    """
    from dataclasses import replace
    return [
        replace(block, confidence=calibrate_confidence(block.confidence, engine_name=engine_name))
        for block in blocks
    ]


def confidence_gate(
    avg_confidence: float,
    *,
    auto_accept_threshold: float = 0.90,
    review_threshold: float = 0.75,
    reject_threshold: float = 0.50,
) -> str:
    """Route based on calibrated confidence to quality gate.

    Returns:
        "accept" — high confidence, safe for automation
        "review" — medium confidence, needs human review
        "reject" — low confidence, likely garbage
    """
    if avg_confidence >= auto_accept_threshold:
        return "accept"
    if avg_confidence >= review_threshold:
        return "review"
    if avg_confidence >= reject_threshold:
        return "review"  # Still send to review, not outright reject
    return "reject"


def engine_temperature(engine_name: str) -> float:
    """Get the calibration temperature for an engine."""
    return _ENGINE_TEMPERATURES.get(engine_name, 1.0)


def update_engine_temperature(engine_name: str, temperature: float) -> None:
    """Update calibration temperature (for runtime tuning)."""
    _ENGINE_TEMPERATURES[engine_name] = max(0.1, min(5.0, temperature))


def calibration_status() -> dict[str, Any]:
    """Return current calibration configuration for diagnostics."""
    return {
        "engine_temperatures": dict(_ENGINE_TEMPERATURES),
        "method": "temperature_scaling",
    }
