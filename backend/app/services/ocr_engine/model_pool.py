"""Model singleton pool — caches expensive OCR model instances.

Aligned with production best practices from GOT-OCR, Surya, and MinerU:
- Load model once per process, reuse across requests
- Optional warmup pass to pre-compile ONNX graphs and allocate GPU memory
- Thread-safe lazy initialization
- Automatic eviction when config changes

This eliminates 2-5s PaddleOCR init and 1-3s ONNX compilation per request.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_lock = threading.Lock()
_pool: dict[str, Any] = {}
_pool_meta: dict[str, dict[str, Any]] = {}


def get_or_create(
    key: str,
    factory: Callable[[], T],
    *,
    warmup: Callable[[T], None] | None = None,
    config_hash: str = "",
) -> T:
    """Get a cached model instance or create one via factory.

    Uses double-check locking to prevent race conditions where two threads
    both see 'key not in pool' and both call factory() — which would cause
    PaddleX/PPStructureV3 double-init crashes.

    Args:
        key: Unique identifier for the model (e.g. "rapidocr_dml_server").
        factory: Callable that creates the model instance.
        warmup: Optional callable to warm up the model (dummy inference).
        config_hash: Hash of current config. If it changes, model is recreated.

    Returns:
        Cached or newly created model instance.
    """
    # Fast path — read under lock (avoids double-init on concurrent requests)
    with _lock:
        existing_meta = _pool_meta.get(key, {})
        if key in _pool and existing_meta.get("config_hash") == config_hash:
            existing_meta["hit_count"] = existing_meta.get("hit_count", 0) + 1
            return _pool[key]

        # Slow path — build under the SAME lock to prevent double-init.
        # PaddleX (PPStructureV3) and ONNX sessions crash on re-initialization.
        # We hold the lock for the full factory() call duration.
        t0 = time.monotonic()
        try:
            instance = factory()
        except Exception:
            logger.warning("model_pool: failed to create '%s'", key, exc_info=True)
            raise
        load_ms = (time.monotonic() - t0) * 1000

        # Optional warmup (still under lock — prevents concurrent use before ready)
        warmup_ms = 0.0
        if warmup is not None:
            tw = time.monotonic()
            try:
                warmup(instance)
            except Exception as exc:
                logger.warning("model_pool: warmup failed for '%s': %s", key, exc)
            warmup_ms = (time.monotonic() - tw) * 1000

        _pool[key] = instance
        _pool_meta[key] = {
            "config_hash": config_hash,
            "created_at": time.time(),
            "load_ms": round(load_ms, 1),
            "warmup_ms": round(warmup_ms, 1),
            "hit_count": 0,
        }

    logger.info(
        "model_pool: created '%s' in %.0fms (warmup: %.0fms, config: %s)",
        key, load_ms, warmup_ms, config_hash[:16] or "default",
    )
    return instance



def evict(key: str) -> bool:
    """Evict a model from the pool."""
    with _lock:
        if key in _pool:
            del _pool[key]
            _pool_meta.pop(key, None)
            logger.info("model_pool: evicted '%s'", key)
            return True
    return False


def evict_all() -> int:
    """Evict all models from the pool."""
    with _lock:
        count = len(_pool)
        _pool.clear()
        _pool_meta.clear()
    if count:
        logger.info("model_pool: evicted all %d models", count)
    return count


def pool_status() -> dict[str, Any]:
    """Return diagnostic status of the model pool."""
    with _lock:
        return {
            "model_count": len(_pool),
            "models": {
                key: {
                    "config_hash": meta.get("config_hash", "")[:16],
                    "load_ms": meta.get("load_ms", 0),
                    "warmup_ms": meta.get("warmup_ms", 0),
                    "hit_count": meta.get("hit_count", 0),
                }
                for key, meta in _pool_meta.items()
            },
        }
