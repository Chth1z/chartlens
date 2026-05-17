"""Concurrency utilities for OCR page processing.

Provides page-level parallel rendering and per-page timeout protection
to prevent single-page hangs from blocking entire document processing.
"""

from __future__ import annotations

import concurrent.futures
import logging
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Default limits — conservative for DirectML GPU memory safety
DEFAULT_PAGE_TIMEOUT_SECONDS = 120
DEFAULT_PAGE_WORKERS = 1  # Serial by default; set > 1 for CPU-only engines


def process_pages_parallel(
    page_inputs: list[Any],
    process_fn: Callable[[Any], T],
    *,
    max_workers: int = DEFAULT_PAGE_WORKERS,
    page_timeout_seconds: float = DEFAULT_PAGE_TIMEOUT_SECONDS,
    label: str = "page",
) -> list[tuple[Any, T | None, str | None]]:
    """Process pages with optional parallelism and per-page timeout.

    Returns list of (input, result_or_None, error_or_None) tuples.
    Order is preserved to match input order.
    """
    if not page_inputs:
        return []

    # Serial path for max_workers=1 (default — safest for GPU)
    if max_workers <= 1:
        return _process_serial(page_inputs, process_fn, page_timeout_seconds=page_timeout_seconds, label=label)

    # Parallel path for CPU-only engines
    return _process_parallel(page_inputs, process_fn, max_workers=max_workers,
                             page_timeout_seconds=page_timeout_seconds, label=label)


def _process_serial(page_inputs, process_fn, *, page_timeout_seconds, label):
    results = []
    for idx, page_input in enumerate(page_inputs):
        try:
            if page_timeout_seconds > 0:
                result = _run_with_timeout(process_fn, page_input, timeout=page_timeout_seconds)
            else:
                result = process_fn(page_input)
            results.append((page_input, result, None))
        except TimeoutError:
            error = f"{label} {idx + 1} exceeded timeout of {page_timeout_seconds}s"
            logger.warning(error)
            results.append((page_input, None, error))
        except Exception as exc:
            error = f"{label} {idx + 1} failed: {exc}"
            logger.warning(error)
            results.append((page_input, None, error))
    return results


def _process_parallel(page_inputs, process_fn, *, max_workers, page_timeout_seconds, label):
    results: list[tuple[Any, Any, str | None]] = [(pi, None, None) for pi in page_inputs]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {}
        for idx, page_input in enumerate(page_inputs):
            future = executor.submit(process_fn, page_input)
            future_to_idx[future] = idx

        timeout = page_timeout_seconds if page_timeout_seconds > 0 else None
        done, not_done = concurrent.futures.wait(future_to_idx.keys(), timeout=timeout)

        for future in done:
            idx = future_to_idx[future]
            try:
                result = future.result(timeout=0)
                results[idx] = (page_inputs[idx], result, None)
            except Exception as exc:
                results[idx] = (page_inputs[idx], None, f"{label} {idx + 1} failed: {exc}")

        for future in not_done:
            idx = future_to_idx[future]
            future.cancel()
            results[idx] = (page_inputs[idx], None, f"{label} {idx + 1} timed out after {page_timeout_seconds}s")

    return results


def run_with_timeout(fn, arg, *, timeout):
    """Run function with timeout using a thread (Windows-compatible, no signal)."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fn, arg)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise TimeoutError(f"Operation timed out after {timeout}s")


_run_with_timeout = run_with_timeout
