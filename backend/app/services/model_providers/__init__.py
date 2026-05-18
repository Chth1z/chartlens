from __future__ import annotations

import httpx

from app.services.model_auth import explicit_api_keys_for_profile

from app.services.model_providers.api import (
    activate_provider_model,
    build_model_profile,
    provider_payload,
    update_provider,
)
from app.services.model_providers.catalog import provider_catalog
from app.services.model_providers.discovery import _fetch_models, fetch_provider_models
from app.services.model_providers.types import (
    ProviderCatalogEntry,
    ProviderModel,
    ProviderSettingsUpdate,
    StoredProviderSettings,
)


__all__ = [
    "ProviderCatalogEntry",
    "ProviderModel",
    "ProviderSettingsUpdate",
    "StoredProviderSettings",
    "activate_provider_model",
    "build_model_profile",
    "fetch_provider_models",
    "provider_catalog",
    "provider_payload",
    "update_provider",
]
