from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthUser:
    sub: str
    email: str | None = None
    name: str | None = None
