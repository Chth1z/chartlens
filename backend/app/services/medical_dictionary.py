from __future__ import annotations

from app.services.system_config import load_system_config


def terms_for_field(field_key: str) -> list[str]:
    config = load_system_config()
    return list(dict.fromkeys(config.medical_dictionaries.history_fields.get(field_key, [])))


def negation_terms() -> list[str]:
    config = load_system_config()
    return list(dict.fromkeys(config.medical_dictionaries.negation_terms))


def unknown_terms() -> list[str]:
    config = load_system_config()
    return list(dict.fromkeys(config.medical_dictionaries.unknown_terms))
