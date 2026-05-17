from __future__ import annotations
import json
import re
import base64
import hashlib
import mimetypes
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import httpx

from app.core.config_loader import load_document_profile, load_extraction_schema
from app.core.settings import settings
from app.domain.models import (
    DocumentIR, DocumentContext, DocumentIRBlock, EvidenceCandidate,
    ExtractedFact, ExtractionCandidate, FieldDecision, FieldDefinition,
    FieldGroup, RemoteExposurePolicy
)
from app.services.document_context import document_context_payload
from app.services.evidence import build_evidence_packs
from app.services.domain_profile import extraction_rules, extraction_system_prompt
from app.services.model_auth import api_keys_for_profile
from app.services.model_selection import get_active_model_profile, resolve_model_chain
from app.services.safe_errors import safe_error_message
from .types import SemanticExtractionProvider, _unknown_model_unavailable
from .local_extraction import ConservativeLocalProvider
from .utils import _format_provider_failure, _is_failover_worthy, _model_ref

from .adapters import OpenAIResponsesProvider, OpenAICompatibleChatProvider, AnthropicMessagesProvider, GoogleGeminiProvider

class ModelFallbackProvider(SemanticExtractionProvider):
    name = "openclaw-style-model-fallback"
    route = "model_fallback"

    def __init__(self, profiles) -> None:
        self.profiles = profiles

    def extract_group(
        self,
        *,
        document_ir: DocumentIR,
        group: FieldGroup,
        fields: list[FieldDefinition],
        blocks: list[DocumentIRBlock],
    ) -> list[ExtractionCandidate]:
        failures: list[str] = []
        for profile in self.profiles:
            try:
                provider = _provider_for_profile(profile)
                result = provider.extract_group(document_ir=document_ir, group=group, fields=fields, blocks=blocks)
                self.name = provider.name
                self.route = provider.route
                self.last_usage = {
                    **provider.last_usage,
                    "fallback_attempts": len(failures),
                }
                if failures:
                    self.last_usage["fallback_errors"] = failures
                return result
            except Exception as exc:
                failures.append(_format_provider_failure(profile, exc))
                if not _is_failover_worthy(exc):
                    break
        if fields:
            result = [
                _unknown_model_unavailable(field, "LLM_PROVIDER_FAILED", "语义模型链路不可用，复杂字段保持 unknown 并进入复核。")
                for field in fields
            ]
            self.name = "unknown-after-model-fallback"
            self.route = "unknown_after_model_fallback"
        else:
            fallback = ConservativeLocalProvider()
            result = fallback.extract_group(document_ir=document_ir, group=group, fields=fields, blocks=blocks)
            self.name = fallback.name
            self.route = "local_after_model_fallback"
        self.last_usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_input_tokens": 0,
            "cost_usd": 0.0,
            "fallback_attempts": len(failures),
            "fallback_failures": len(failures),
            "fallback_errors": failures,
        }
        return result

    def collect_evidence(
        self,
        *,
        document_context: DocumentContext,
        fields: list[FieldDefinition],
    ) -> dict[str, list[EvidenceCandidate]]:
        failures: list[str] = []
        for profile in self.profiles:
            try:
                provider = _provider_for_profile(profile)
                result = provider.collect_evidence(document_context=document_context, fields=fields)
                self.name = provider.name
                self.route = provider.route
                self.last_usage = {**provider.last_usage, "fallback_attempts": len(failures)}
                if failures:
                    self.last_usage["fallback_errors"] = failures
                return result
            except Exception as exc:
                failures.append(_format_provider_failure(profile, exc))
                if not _is_failover_worthy(exc):
                    break
        fallback = ConservativeLocalProvider()
        result = fallback.collect_evidence(document_context=document_context, fields=fields)
        self.name = fallback.name
        self.route = fallback.route
        self.last_usage = {
            **fallback.last_usage,
            "fallback_attempts": len(failures),
            "fallback_failures": len(failures),
            "fallback_errors": failures,
        }
        return result


def build_semantic_provider() -> SemanticExtractionProvider:
    active = get_active_model_profile()
    if active.provider == "disabled" or settings.llm_mode == "disabled":
        return ConservativeLocalProvider()
    return ModelFallbackProvider(resolve_model_chain(active))


def _provider_for_profile(profile) -> SemanticExtractionProvider:
    if profile.provider == "disabled":
        return ConservativeLocalProvider()
    if profile.provider == "openai_responses" and settings.llm_mode in {"auto", "online"}:
        return OpenAIResponsesProvider(profile)
    if profile.provider == "openai_compatible" and settings.llm_mode in {"auto", "online", "local"}:
        return OpenAICompatibleChatProvider(profile)
    if profile.provider == "anthropic_messages" and settings.llm_mode in {"auto", "online"}:
        return AnthropicMessagesProvider(profile)
    if profile.provider == "google_gemini" and settings.llm_mode in {"auto", "online"}:
        return GoogleGeminiProvider(profile)
    raise RuntimeError(f"Model profile is not runnable in current mode: {_model_ref(profile)}")

