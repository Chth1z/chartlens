"""Model profile and model provider routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.contracts import (
    ModelProfileSelectionResponse,
    ModelProfilesResponse,
    ModelProviderActivationResponse,
    ModelProviderFetchResponse,
    ModelProviderUpdateResponse,
    ModelProvidersResponse,
)
from app.services.model_providers import (
    ProviderSettingsUpdate,
    activate_provider_model,
    fetch_provider_models,
    provider_payload,
    update_provider,
)
from app.services.model_selection import model_profiles_payload, set_active_model_profile


router = APIRouter()


class ModelSelectionPayload(BaseModel):
    profile_id: str


class ActiveProviderModelPayload(BaseModel):
    provider_id: str
    model_id: str


@router.get("/model-profiles", response_model=ModelProfilesResponse)
def get_model_profiles() -> dict:
    return model_profiles_payload()


@router.patch("/model-profiles/active", response_model=ModelProfileSelectionResponse)
def update_active_model_profile(payload: ModelSelectionPayload) -> dict:
    try:
        active = set_active_model_profile(payload.profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "active": active.model_dump(), **model_profiles_payload()}


@router.get("/model-providers", response_model=ModelProvidersResponse)
def get_model_providers() -> dict:
    return provider_payload()


@router.patch("/model-providers/active", response_model=ModelProviderActivationResponse)
def update_active_provider_model(payload: ActiveProviderModelPayload) -> dict:
    try:
        return activate_provider_model(payload.provider_id, payload.model_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/model-providers/{provider_id}", response_model=ModelProviderUpdateResponse)
def update_model_provider(provider_id: str, payload: ProviderSettingsUpdate) -> dict:
    try:
        return {"ok": True, "provider": update_provider(provider_id, payload)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/model-providers/{provider_id}/models/fetch", response_model=ModelProviderFetchResponse)
def fetch_models_for_provider(provider_id: str) -> dict:
    try:
        return fetch_provider_models(provider_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
