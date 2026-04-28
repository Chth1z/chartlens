from __future__ import annotations

from app.core.config import settings
from app.infrastructure.config.field_dictionary import load_field_dictionary
from app.infrastructure.config.system_config import load_system_config


class YamlFieldDictionaryProvider:
    def load_field_dictionary(self):
        return load_field_dictionary()


class YamlSystemConfigProvider:
    def load_system_config(self):
        return load_system_config()


class EnvRuntimeSettings:
    @property
    def sync_pipeline(self) -> bool:
        return settings.sync_pipeline
