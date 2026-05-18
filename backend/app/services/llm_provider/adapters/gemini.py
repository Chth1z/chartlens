from __future__ import annotations
from typing import Any
import httpx

from app.core.settings import settings
from app.domain.models import (
    DocumentIR, DocumentContext, DocumentIRBlock, EvidenceCandidate,
    ExtractionCandidate, FieldDefinition, FieldGroup,
)
from app.services.model_selection import get_active_model_profile
from app.services.safe_errors import safe_error_message
from app.services.llm_provider import adapters as _pkg
from ..types import SemanticExtractionProvider, local_collect_evidence_fallback, local_evidence_fallback_usage
from ..utils import _base_url_for_profile, _api_keys_for_attempts, _is_rate_limit_or_timeout, _mark_api_key_cooldown, _model_for_profile, _model_ref
from ..payloads import _requires_local_evidence_collection, _remote_exposure_policy, _remote_context_mode, _gemini_payload, _gemini_evidence_first_payload
from ..cache import _cache_hit_usage, _cache_miss_usage, _evidence_first_cache_key
from ..parsing import _candidates_from_text, _evidence_candidates_from_text, _gemini_text


class GoogleGeminiProvider(SemanticExtractionProvider):
    name = "google-gemini"
    route = "gemini_llm"

    def __init__(self, profile=None) -> None:
        self.profile = profile or get_active_model_profile()
        self.api_keys = _pkg.api_keys_for_profile(self.profile)
        if not self.api_keys:
            raise RuntimeError(f"API key is required for {_model_ref(self.profile)}")
        self.base_url = (_base_url_for_profile(self.profile) or "https://generativelanguage.googleapis.com").rstrip("/")
        self.model = _model_for_profile(self.profile)

    def extract_group(
        self,
        *,
        document_ir: DocumentIR,
        group: FieldGroup,
        fields: list[FieldDefinition],
        blocks: list[DocumentIRBlock],
    ) -> list[ExtractionCandidate]:
        cache_key = _pkg._llm_cache_key(self.profile, document_ir, group, fields, blocks)
        cached = _pkg._read_llm_result_cache(cache_key)
        if cached is not None:
            self.last_usage = _cache_hit_usage(cache_key)
            return cached
        payload = _gemini_payload(
            document_ir=document_ir,
            group=group,
            fields=fields,
            blocks=blocks,
            model=self.model,
            profile=self.profile,
        )
        last_error: Exception | None = None
        for api_key in _api_keys_for_attempts(self.profile, self.api_keys):
            try:
                with httpx.Client(timeout=settings.openai_timeout_seconds) as client:
                    response = client.post(
                        f"{self.base_url}/v1beta/models/{self.model}:generateContent",
                        params={"key": api_key},
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()
                break
            except Exception as exc:
                last_error = exc
                if not _is_rate_limit_or_timeout(exc):
                    raise
                _mark_api_key_cooldown(self.profile, api_key, exc)
        else:
            raise last_error or RuntimeError("Gemini request failed")
        usage = data.get("usageMetadata", {})
        self.last_usage = {
            "input_tokens": int(usage.get("promptTokenCount") or 0),
            "output_tokens": int(usage.get("candidatesTokenCount") or 0),
            "cached_input_tokens": int(usage.get("cachedContentTokenCount") or 0),
            "cost_usd": 0.0,
            **_cache_miss_usage(cache_key),
        }
        result = _candidates_from_text(_gemini_text(data))
        _pkg._write_llm_result_cache(cache_key, result)
        return result

    def collect_evidence(
        self,
        *,
        document_context: DocumentContext,
        fields: list[FieldDefinition],
    ) -> dict[str, list[EvidenceCandidate]]:
        """Real implementation: call Gemini generateContent with
        responseMimeType=application/json + responseSchema for the
        evidence-first JSON contract. Falls back to local rule
        extraction on policy block, permanent error, or malformed JSON.

        E1-011 Phase 3 (2026-05-18). Replaces the explicit-delegation
        shim from Phase 1.
        """
        cache_key = _evidence_first_cache_key(self.profile, document_context, fields, stage="collect")
        cached = _pkg._read_evidence_candidate_cache(cache_key)
        if cached is not None:
            self.last_usage = _cache_hit_usage(cache_key)
            return cached

        remote_policy = _remote_exposure_policy()
        if _requires_local_evidence_collection(remote_policy):
            result = local_collect_evidence_fallback(document_context, fields)
            self.last_usage = {
                **local_evidence_fallback_usage(),
                "remote_context_mode": _remote_context_mode(remote_policy),
                "remote_skipped_reason": "remote_full_context_disabled",
                **_cache_miss_usage(cache_key),
            }
            _pkg._write_evidence_candidate_cache(cache_key, result)
            return result

        payload = _gemini_evidence_first_payload(
            document_context=document_context,
            fields=fields,
            model=self.model,
            profile=self.profile,
        )

        last_error: Exception | None = None
        data: dict[str, Any] | None = None
        for api_key in _api_keys_for_attempts(self.profile, self.api_keys):
            try:
                with httpx.Client(timeout=settings.openai_timeout_seconds) as client:
                    response = client.post(
                        f"{self.base_url}/v1beta/models/{self.model}:generateContent",
                        params={"key": api_key},
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()
                break
            except Exception as exc:
                last_error = exc
                if not _is_rate_limit_or_timeout(exc):
                    return self._gemini_evidence_local_fallback(
                        document_context=document_context,
                        fields=fields,
                        cache_key=cache_key,
                        failure=exc,
                        failure_reason="permanent_error",
                    )
                _mark_api_key_cooldown(self.profile, api_key, exc)

        if data is None:
            return self._gemini_evidence_local_fallback(
                document_context=document_context,
                fields=fields,
                cache_key=cache_key,
                failure=last_error,
                failure_reason="no_response",
            )

        try:
            text = _gemini_text(data)
            result = _evidence_candidates_from_text(text)
        except Exception as exc:
            return self._gemini_evidence_local_fallback(
                document_context=document_context,
                fields=fields,
                cache_key=cache_key,
                failure=exc,
                failure_reason="malformed_json",
            )

        usage = data.get("usageMetadata", {}) or {}
        self.last_usage = {
            "input_tokens": int(usage.get("promptTokenCount") or 0),
            "output_tokens": int(usage.get("candidatesTokenCount") or 0),
            "cached_input_tokens": int(usage.get("cachedContentTokenCount") or 0),
            "cost_usd": 0.0,
            "evidence_collection_method": "remote_gemini_generate_content",
            **_cache_miss_usage(cache_key),
        }
        _pkg._write_evidence_candidate_cache(cache_key, result)
        return result

    def _gemini_evidence_local_fallback(
        self,
        *,
        document_context: DocumentContext,
        fields: list[FieldDefinition],
        cache_key: str,
        failure: Exception | None,
        failure_reason: str,
    ) -> dict[str, list[EvidenceCandidate]]:
        result = local_collect_evidence_fallback(document_context, fields)
        self.last_usage = {
            **local_evidence_fallback_usage(),
            "remote_skipped_reason": failure_reason,
            "remote_failure": safe_error_message(failure) if failure is not None else None,
            **_cache_miss_usage(cache_key),
        }
        return result
