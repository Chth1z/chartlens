"""Structured-output capability detection and downgrade ladder.

This module contains the constants, helpers, and exception class used by
OpenAI-compatible chat adapters to detect 400-class capability rejections
and downgrade to a weaker structured_output_mode.

Extracted from openai_compatible.py for single-file complexity governance.
"""
from __future__ import annotations

from app.services.safe_errors import safe_error_message


# Downgrade ladder used when the upstream rejects the active
# `structured_output_mode` with a 400-class capability error
# (M1-001). Per docs/MODERNIZATION_PLAN.md:
#   json_schema -> json_object -> text
# `tools` is not on the chat-completions ladder; profiles that declare
# `tools` are routed through a different adapter shape and do not
# downgrade through this path.
_CHAT_DOWNGRADE_NEXT: dict[str, str] = {
    "json_schema": "json_object",
    "json_object": "text",
}


def _next_chat_structured_output_mode(mode: str) -> str | None:
    """Return the next-weaker structured_output_mode for the OpenAI-
    compatible chat path, or None if the mode is already at the bottom
    of the ladder.
    """
    return _CHAT_DOWNGRADE_NEXT.get(mode)


_CAPABILITY_MARKERS: tuple[str, ...] = (
    "response_format",
    "json_schema",
    "unsupported",
    "not supported",
    "invalid_request_error",
)


def _is_structured_output_capability_error(exc: Exception) -> bool:
    """Detect a 400-class rejection that names structured-output
    capabilities. The upstream provider does not support the
    `response_format` shape we sent and we should downgrade to a
    weaker mode.

    Match rule:
      status_code == 400 (or message-derived 400/"bad request") AND
      message contains one of the capability markers.

    Examples that match:
      "400 Bad Request: response_format json_schema not supported"
      "invalid_request_error: response_format type 'json_schema' is unsupported"
    """
    text = str(exc).lower()
    status = getattr(exc, "status_code", None)
    is_400 = status == 400 or "400" in text or "bad request" in text
    if not is_400:
        return False
    return any(marker in text for marker in _CAPABILITY_MARKERS)


class _StructuredOutputCapabilityError(Exception):
    """Internal signal that the upstream rejected the active
    `structured_output_mode`. Wraps the original exception so the
    capability-fallback shell can retry once with a weaker mode.
    """

    def __init__(self, original: Exception) -> None:
        super().__init__(safe_error_message(original))
        self.original = original
