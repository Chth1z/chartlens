from abc import ABC, abstractmethod
from typing import Any
from app.domain.models import DocumentIR, DocumentContext, DocumentIRBlock, EvidenceCandidate, ExtractionCandidate, FieldDecision, FieldDefinition, FieldGroup


def local_collect_evidence_fallback(
    document_context: DocumentContext,
    fields: list[FieldDefinition],
) -> dict[str, list[EvidenceCandidate]]:
    """Run the rule-driven local evidence collector.

    This is the canonical fallback path that any LLM adapter may call when
    its remote evidence-collection implementation is intentionally not yet
    in place, or when a remote call must degrade gracefully (HTTP error,
    malformed JSON, rate limit). Adapters that delegate to this function
    must do so explicitly; the base class no longer offers this behavior
    as a default override.

    See `docs/LLM_PROVIDER_REFACTOR.md` for the architectural rule.
    """
    from app.services.evidence_first import collect_local_evidence

    return collect_local_evidence(document_context, fields)


def local_evidence_fallback_usage() -> dict[str, Any]:
    """The standard `last_usage` payload for an adapter that delegates to
    `local_collect_evidence_fallback`. Surfaces the fallback in diagnostics
    via `evidence_collection_method=local_fallback` so a runtime ledger
    query can find the runs that did not actually call the LLM."""
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_input_tokens": 0,
        "cost_usd": 0.0,
        "evidence_collection_method": "local_fallback",
    }


class SemanticExtractionProvider(ABC):
    name = "semantic-provider"
    route = "unknown"
    last_usage: dict[str, Any] = {}

    @abstractmethod
    def extract_group(
        self,
        *,
        document_ir: DocumentIR,
        group: FieldGroup,
        fields: list[FieldDefinition],
        blocks: list[DocumentIRBlock],
    ) -> list[ExtractionCandidate]:
        raise NotImplementedError

    @abstractmethod
    def collect_evidence(
        self,
        *,
        document_context: DocumentContext,
        fields: list[FieldDefinition],
    ) -> dict[str, list[EvidenceCandidate]]:
        """Collect per-field evidence candidates from the de-identified
        DocumentContext.

        Adapters MUST implement this method explicitly. To preserve the
        previous "delegate to local rule extraction" behavior, an adapter
        may return `local_collect_evidence_fallback(document_context, fields)`
        directly and assign `local_evidence_fallback_usage()` to
        `self.last_usage`. The choice between calling the upstream API and
        delegating to local extraction must be visible in the adapter's
        source rather than implicit through inheritance.

        See `docs/DECISIONS.md` 2026-05-18 "Default-inheritance shim for
        collect_evidence is forbidden" and `docs/LLM_PROVIDER_REFACTOR.md`.
        """
        raise NotImplementedError

    def adjudicate_fields(
        self,
        *,
        document_context: DocumentContext,
        fields: list[FieldDefinition],
        evidence_by_field: dict[str, list[EvidenceCandidate]],
    ) -> dict[str, FieldDecision]:
        del document_context
        from app.services.evidence_first import adjudicate_field_decisions

        return adjudicate_field_decisions(fields, evidence_by_field)

    # --- Async adapter methods (optional, non-abstract) ----------------------
    # Default implementations wrap the sync method in asyncio.to_thread so
    # that subclasses without a native async path still work when called from
    # an async context. Providers with a true async SDK (e.g. AsyncOpenAI)
    # override these for genuine non-blocking I/O.

    async def async_extract_group(
        self,
        *,
        document_ir: DocumentIR,
        group: FieldGroup,
        fields: list[FieldDefinition],
        blocks: list[DocumentIRBlock],
    ) -> list[ExtractionCandidate]:
        """Async version of extract_group. Default wraps sync in to_thread."""
        import asyncio
        return await asyncio.to_thread(
            self.extract_group, document_ir=document_ir, group=group, fields=fields, blocks=blocks
        )

    async def async_collect_evidence(
        self,
        *,
        document_context: DocumentContext,
        fields: list[FieldDefinition],
    ) -> dict[str, list[EvidenceCandidate]]:
        """Async version of collect_evidence. Default wraps sync in to_thread."""
        import asyncio
        return await asyncio.to_thread(
            self.collect_evidence, document_context=document_context, fields=fields
        )

    def verify_against_document(
        self,
        *,
        document_context: DocumentContext,
        fields: list[FieldDefinition],
        decisions_by_field: dict[str, FieldDecision],
    ) -> dict[str, FieldDecision]:
        del document_context, fields
        return decisions_by_field


def _unknown_model_unavailable(field: FieldDefinition, error_code: str, summary: str) -> ExtractionCandidate:
    return ExtractionCandidate(
        field_key=field.key,
        field_group_key=field.field_group_key,
        normalized_code="unknown",
        status="error",
        confidence=0.0,
        evidence_type="no_evidence",
        reasoning_summary=summary,
        review_required=True,
        error_code=error_code,
        provenance={"source": "model_fallback"},
        acceptance_reason=error_code,
        risk_level="high",
        validation_state="needs_review",
    )


async def run_provider_async(
    provider: SemanticExtractionProvider,
    method: str,
    **kwargs: Any,
) -> Any:
    """Call the async version of a provider method when available, falling
    back to the sync method wrapped in asyncio.to_thread.

    This utility allows the pipeline to call async methods when available
    without requiring all callers to know whether a provider has a native
    async implementation.

    Parameters
    ----------
    provider : SemanticExtractionProvider
        The provider instance to call.
    method : str
        The method name, e.g. "collect_evidence" or "extract_group".
    **kwargs
        Keyword arguments forwarded to the method.

    Returns
    -------
    The result of the provider method call.
    """
    import asyncio

    async_method_name = f"async_{method}"
    async_method = getattr(provider, async_method_name, None)
    if async_method is not None and callable(async_method):
        return await async_method(**kwargs)
    # Fallback: wrap the sync method in to_thread
    sync_method = getattr(provider, method)
    return await asyncio.to_thread(sync_method, **kwargs)
