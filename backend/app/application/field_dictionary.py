from __future__ import annotations

from app.application.ports import FieldDictionaryProvider


class GetFieldDictionary:
    def __init__(self, provider: FieldDictionaryProvider):
        self.provider = provider

    def execute(self) -> dict:
        return self.provider.load_field_dictionary().model_dump()
