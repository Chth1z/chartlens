from __future__ import annotations

from pydantic import BaseModel

from app.application.ports import SettingsStatusProvider


class SettingsValidationRequest(BaseModel):
    system_config_yaml: str | None = None
    field_dictionary_yaml: str | None = None


class GetSystemSettings:
    def __init__(self, provider: SettingsStatusProvider):
        self.provider = provider

    def execute(self) -> dict:
        return self.provider.system_settings_payload()


class GetFieldDictionarySettings:
    def __init__(self, provider: SettingsStatusProvider):
        self.provider = provider

    def execute(self) -> dict:
        return self.provider.field_dictionary_payload()


class GetRuntimeSettings:
    def __init__(self, provider: SettingsStatusProvider):
        self.provider = provider

    def execute(self) -> dict:
        return self.provider.runtime_settings_payload()


class ValidateSettings:
    def __init__(self, provider: SettingsStatusProvider):
        self.provider = provider

    def execute(self, request: SettingsValidationRequest) -> dict:
        return self.provider.validate_settings_payload(request)
