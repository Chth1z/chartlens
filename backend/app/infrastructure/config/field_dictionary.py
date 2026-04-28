from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from app.domain.field_definitions import FieldDefinition, FieldDictionary, LlmPolicy


DICTIONARY_PATH = Path(__file__).resolve().parents[2] / "data" / "field_dictionary.yaml"


@lru_cache(maxsize=1)
def load_field_dictionary(path: str | Path | None = None) -> FieldDictionary:
    dictionary_path = Path(path) if path else DICTIONARY_PATH
    with dictionary_path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    return FieldDictionary.model_validate(payload)
