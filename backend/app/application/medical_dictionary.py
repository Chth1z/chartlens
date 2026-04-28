from __future__ import annotations

DEFAULT_HISTORY_FIELDS: dict[str, list[str]] = {}
DEFAULT_NEGATION_TERMS: list[str] = []
DEFAULT_UNKNOWN_TERMS: list[str] = []


def terms_for_field(field_key: str, history_fields: dict[str, list[str]] | None = None) -> list[str]:
    source = history_fields if history_fields is not None else DEFAULT_HISTORY_FIELDS
    return list(dict.fromkeys(source.get(field_key, [])))


def negation_terms(values: list[str] | None = None) -> list[str]:
    return list(dict.fromkeys(values if values is not None else DEFAULT_NEGATION_TERMS))


def unknown_terms(values: list[str] | None = None) -> list[str]:
    return list(dict.fromkeys(values if values is not None else DEFAULT_UNKNOWN_TERMS))
