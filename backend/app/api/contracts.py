from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ExtensiblePayload(BaseModel):
    model_config = ConfigDict(extra="allow")


class HealthResponse(BaseModel):
    ok: bool
    app: str
    config_errors: list[str]


class ConfigResponse(BaseModel):
    schema_: dict[str, Any] = Field(alias="schema")
    export_template: dict[str, Any]
    config_errors: list[str]


class UserIdentity(BaseModel):
    sub: str
    email: str | None = None
    name: str | None = None


class SessionAuthStatus(BaseModel):
    enabled: bool
    authenticated: bool
    provider: str
    user: UserIdentity | None = None
    issued_at: int | None = None
    expires_at: int | None = None
    cookie_name: str


class ModelAuthStatus(BaseModel):
    auth_mode: Literal["auto", "online", "local", "disabled"]
    provider: str
    online_model_available: bool
    api_key_configured: bool
    chatgpt_codex_configured: bool
    token_cache_exists: bool
    token_cache_path: str
    updated_at: str | int | None = None
    expires_at: str | int | None = None
    user: UserIdentity | None = None


class AuthStatusResponse(BaseModel):
    enabled: bool
    auth_provider: Literal["chatgpt", "oidc"]
    configured: bool
    missing_config: list[str]
    config_warnings: list[str]
    chatgpt_login_available: bool
    authenticated: bool
    user: UserIdentity | None = None
    session_auth: SessionAuthStatus
    model_auth: ModelAuthStatus


class MaintenanceResponse(BaseModel):
    ok: bool
    affected_count: int = 0
    message: str | None = None


class ModelProfilesResponse(BaseModel):
    active_profile_id: str
    active_model_ref: str | None = None
    fallbacks: list[str] = Field(default_factory=list)
    resolved_chain: list[str] = Field(default_factory=list)
    profiles: list[dict[str, Any]]
    env: dict[str, Any]


class ModelProfileSelectionResponse(ModelProfilesResponse):
    ok: bool
    active: dict[str, Any]


class ModelProvidersResponse(BaseModel):
    active: dict[str, Any]
    providers: list[dict[str, Any]]


class ModelProviderUpdateResponse(BaseModel):
    ok: bool
    provider: dict[str, Any]


class ModelProviderFetchResponse(ExtensiblePayload):
    ok: bool


class ModelProviderActivationResponse(ModelProvidersResponse):
    ok: bool
    active_model: dict[str, Any]


class DocumentIrResponse(ExtensiblePayload):
    blocks: list[dict[str, Any]] = Field(default_factory=list)
    sections: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CaseDiagnosticsResponse(BaseModel):
    case_id: str
    quality: dict[str, Any]
    latest_run: dict[str, Any] | None = None
    run_count: int
    runs: list[dict[str, Any]]
    fragments: list[dict[str, Any]]
    model_calls: list[dict[str, Any]]
    vision_requests: list[dict[str, Any]]
    config: dict[str, Any]


class VisionFallbackRecordResponse(BaseModel):
    request_id: str
    case_id: str
    page: int
    bbox: list[float]
    status: str
    reason: str
    reviewer: str
    created_at: str
    approved_at: str | None = None


class FieldDictionaryResponse(BaseModel):
    version: str
    fields: list[dict[str, Any]]


class ProjectConfigResponse(BaseModel):
    app_profile: dict[str, Any]
    document_profile: dict[str, Any]
    extraction_schema: dict[str, Any]
    export_template: dict[str, Any]


class SystemSettingsResponse(BaseModel):
    system_config: dict[str, Any]


class FieldDictionarySettingsResponse(BaseModel):
    field_dictionary: dict[str, Any]


class RuntimeSettingsResponse(BaseModel):
    runtime_settings: dict[str, Any]
    restart_required_hints: list[str]


class SettingsValidationResponse(BaseModel):
    ok: bool
    validation_errors: list[str]
    restart_required_hints: list[str]


class BatchEvaluationResponse(BaseModel):
    summary: dict[str, Any]
    cases: list[dict[str, Any]]


class EvaluationProfileRunResponse(BatchEvaluationResponse):
    profile: dict[str, Any]
