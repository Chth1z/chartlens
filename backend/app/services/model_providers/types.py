from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ProviderApi = Literal["openai-responses", "openai-completions", "anthropic-messages", "google-gemini", "disabled"]
ModelSource = Literal["fetched", "custom", "preset"]


class ProviderModel(BaseModel):
    id: str
    name: str | None = None
    context_window: int | None = None
    max_tokens: int | None = None
    input: list[str] = Field(default_factory=lambda: ["text"])
    source: ModelSource | None = None
    runnable: bool | None = None


class ProviderCatalogEntry(BaseModel):
    provider_id: str
    label: str
    description: str
    api: ProviderApi
    api_options: list[ProviderApi] = Field(default_factory=list)
    default_base_url: str | None = None
    auth_env_vars: list[str] = Field(default_factory=list)
    auth_optional: bool = False
    base_url_editable: bool = True
    default_models: list[ProviderModel] = Field(default_factory=list)
    option_schema: dict[str, Any] = Field(default_factory=dict)


class StoredProviderSettings(BaseModel):
    provider_id: str
    enabled: bool = True
    api: ProviderApi | None = None
    api_key: str | None = None
    base_url: str | None = None
    selected_model: str | None = None
    custom_models: list[ProviderModel] = Field(default_factory=list)
    fetched_models: list[ProviderModel] = Field(default_factory=list)
    model_settings: dict[str, Any] = Field(default_factory=dict)
    last_error: str | None = None
    connected_at: str | None = None


class ProviderSettingsUpdate(BaseModel):
    enabled: bool | None = None
    api: ProviderApi | None = None
    api_key: str | None = None
    base_url: str | None = None
    selected_model: str | None = None
    custom_models: list[ProviderModel] | None = None
    model_settings: dict[str, Any] | None = None
