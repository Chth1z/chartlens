"""Optional config file watcher for hot-reload.

Monitors the config directory for file changes and invalidates the
config cache when a YAML file is modified. Runs in a daemon thread
so it doesn't block shutdown.

Enabled by default; disable with EYEX_CONFIG_WATCH=false.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from app.core.settings import settings

logger = logging.getLogger(__name__)

_watcher_thread: threading.Thread | None = None
_stop_event = threading.Event()


def start_config_watcher() -> None:
    """Start the config file watcher daemon thread."""
    global _watcher_thread

    if not settings.config_watch:
        logger.info("Config watcher disabled (EYEX_CONFIG_WATCH=false)")
        return

    if _watcher_thread is not None and _watcher_thread.is_alive():
        return

    config_dir = settings.config_dir
    if not config_dir.exists():
        logger.warning("Config directory %s does not exist; watcher not started", config_dir)
        return

    _stop_event.clear()
    _watcher_thread = threading.Thread(
        target=_watch_loop,
        args=(config_dir,),
        daemon=True,
        name="config-watcher",
    )
    _watcher_thread.start()
    logger.info("Config watcher started for %s", config_dir)


def stop_config_watcher() -> None:
    """Signal the watcher to stop."""
    _stop_event.set()


def _watch_loop(config_dir: Path) -> None:
    """Poll config directory for mtime changes every 2 seconds."""
    from app.core.config_loader import invalidate_config_cache

    # Build initial snapshot of file mtimes
    snapshot = _build_snapshot(config_dir)

    while not _stop_event.is_set():
        _stop_event.wait(timeout=2.0)
        if _stop_event.is_set():
            break

        new_snapshot = _build_snapshot(config_dir)
        if new_snapshot != snapshot:
            changed = set(new_snapshot.keys()) ^ set(snapshot.keys())
            changed.update(
                k for k in new_snapshot
                if k in snapshot and new_snapshot[k] != snapshot[k]
            )
            logger.info("Config change detected in %d file(s), invalidating cache", len(changed))
            invalidate_config_cache()
            snapshot = new_snapshot


def _build_snapshot(config_dir: Path) -> dict[str, float]:
    """Build a dict of relative_path -> mtime for all YAML files."""
    snapshot: dict[str, float] = {}
    try:
        for yaml_file in config_dir.rglob("*.yaml"):
            try:
                snapshot[str(yaml_file.relative_to(config_dir))] = yaml_file.stat().st_mtime
            except OSError:
                pass
    except OSError:
        pass
    return snapshot
