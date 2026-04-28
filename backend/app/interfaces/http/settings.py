from __future__ import annotations

from fastapi import APIRouter, Depends

from app.application.ports import SettingsStatusProvider
from app.application.settings_status import (
    GetFieldDictionarySettings,
    GetRuntimeSettings,
    GetSystemSettings,
    SettingsValidationRequest,
    ValidateSettings,
)
from app.composition.dependencies import get_settings_status_provider
from app.domain.auth import AuthUser
from app.interfaces.http.auth_service import require_user

router = APIRouter(prefix="/api/settings")


@router.get("/system")
def get_system_settings(
    _: AuthUser = Depends(require_user),
    provider: SettingsStatusProvider = Depends(get_settings_status_provider),
) -> dict:
    return GetSystemSettings(provider).execute()


@router.get("/field-dictionary")
def get_field_dictionary_settings(
    _: AuthUser = Depends(require_user),
    provider: SettingsStatusProvider = Depends(get_settings_status_provider),
) -> dict:
    return GetFieldDictionarySettings(provider).execute()


@router.get("/runtime")
def get_runtime_settings(
    _: AuthUser = Depends(require_user),
    provider: SettingsStatusProvider = Depends(get_settings_status_provider),
) -> dict:
    return GetRuntimeSettings(provider).execute()


@router.post("/validate")
def validate_settings(
    request: SettingsValidationRequest | None = None,
    _: AuthUser = Depends(require_user),
    provider: SettingsStatusProvider = Depends(get_settings_status_provider),
) -> dict:
    return ValidateSettings(provider).execute(request or SettingsValidationRequest())
