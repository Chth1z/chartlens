"""Retry and resilience utilities for OCR engine calls.

Aligned with production OCR best practices:
- Exponential backoff with jitter for transient failures
- Classification of retryable vs permanent errors
- Partial result acceptance for graceful degradation
- Structured logging of retry attempts
"""

from __future__ import annotations

import logging
import random
import time
from typing import Callable, TypeVar

from app.services.ocr_engine.errors import OcrErrorCode

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Default retry configuration
DEFAULT_MAX_RETRIES = 2
DEFAULT_BASE_DELAY = 1.0      # seconds
DEFAULT_MAX_DELAY = 8.0       # seconds
DEFAULT_JITTER_RANGE = 0.5    # ± 50% jitter

# Error codes that are worth retrying
RETRYABLE_CODES = frozenset({
    OcrErrorCode.DIRECTML_CRASH,
    OcrErrorCode.DIRECTML_TIMEOUT,
    OcrErrorCode.TIMEOUT,
    OcrErrorCode.MEMORY_EXHAUSTED,
    OcrErrorCode.NETWORK_ERROR,
    OcrErrorCode.SIDECAR_UNAVAILABLE,
})

# Error codes that should NOT be retried
PERMANENT_CODES = frozenset({
    OcrErrorCode.INPUT_INVALID,
    OcrErrorCode.ENGINE_UNAVAILABLE,
})


def is_retryable(exc: Exception) -> bool:
    """Determine if an exception is worth retrying."""
    code = OcrErrorCode.classify(exc)
    if code in PERMANENT_CODES:
        return False
    if code in RETRYABLE_CODES:
        return True
    # Unknown errors — retry only once (conservative)
    return False


def retry_with_backoff(
    fn: Callable[[], T],
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    label: str = "ocr_operation",
) -> T:
    """Execute fn with exponential backoff retry on transient failures.

    Args:
        fn: The callable to execute.
        max_retries: Maximum number of retry attempts (0 = no retry).
        base_delay: Initial delay between retries in seconds.
        max_delay: Maximum delay cap in seconds.
        label: Human-readable label for logging.

    Returns:
        The result of fn() on success.

    Raises:
        The last exception if all retries are exhausted.
    """
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            code = OcrErrorCode.classify(exc)

            if attempt >= max_retries or not is_retryable(exc):
                logger.warning(
                    "%s: failed [%s] after %d attempt(s): %s",
                    label, code.value, attempt + 1, str(exc)[:200],
                )
                raise

            # Calculate delay with exponential backoff + jitter
            delay = min(max_delay, base_delay * (2 ** attempt))
            jitter = delay * random.uniform(-DEFAULT_JITTER_RANGE, DEFAULT_JITTER_RANGE)
            actual_delay = max(0.1, delay + jitter)

            logger.info(
                "%s: retryable error [%s] on attempt %d/%d, "
                "retrying in %.1fs: %s",
                label, code.value, attempt + 1, max_retries + 1,
                actual_delay, str(exc)[:200],
            )
            time.sleep(actual_delay)

    # Should not reach here, but just in case
    if last_exc:
        raise last_exc
    raise RuntimeError(f"{label}: exhausted retries with no result")
