from __future__ import annotations

import re
from typing import Any

_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"sk-[A-Za-z0-9_-]{8,}"), "sk-***"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1***"),
    (
        re.compile(r"(?i)([?&](?:api[_-]?key|key|token|access_token|refresh_token)=)[^&\s'\"<>)]*"),
        r"\1***",
    ),
    (
        re.compile(
            r"(?i)((?:api[_-]?key|token|access[_-]?token|refresh[_-]?token)['\"=:\s]+)"
            r"([A-Za-z0-9_.~+/=-]{8,})"
        ),
        r"\1***",
    ),
)


def safe_error_message(value: Any, *, limit: int = 500) -> str:
    text = str(value).strip() or "request failed"
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text[:limit]
