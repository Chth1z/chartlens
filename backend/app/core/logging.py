"""Structured logging configuration for EYEX.

Configures structlog as the stdlib logging formatter so all log output
(from both EYEX modules and third-party libraries like uvicorn,
sqlalchemy, alembic) is emitted as structured JSON lines (production)
or colored human-readable logs (development).

Call `init_logging()` once at app startup. Existing modules keep using
`logging.getLogger(__name__)` — the structlog formatter handles the
output format transparently.

Settings:
- EYEX_LOG_FORMAT: "json" (default) or "console"
- EYEX_LOG_LEVEL: "INFO" (default), "DEBUG", "WARNING", etc.
"""
from __future__ import annotations

import logging
import sys

import structlog

_initialized = False


def init_logging() -> None:
    """Initialize structlog as the stdlib logging formatter."""
    global _initialized
    if _initialized:
        return
    _initialized = True

    from app.core.settings import settings

    json_mode = getattr(settings, "log_format", "json") == "json"
    log_level = getattr(settings, "log_level", "INFO").upper()

    # Shared processors applied to every log record
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if json_mode:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer(ensure_ascii=False)
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    # Configure structlog for any code that uses structlog.get_logger() directly
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure stdlib logging to use structlog's formatter for output
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    # Only reconfigure root handlers when NOT running under pytest.
    # pytest manages its own log capture; clearing handlers breaks it.
    if "pytest" not in sys.modules:
        root_logger.handlers.clear()
        root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level, logging.INFO))

    # Quiet noisy loggers
    logging.getLogger("alembic").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
