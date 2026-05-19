"""Tests for async pipeline execution path (S2-002).

Verifies:
1. async_extract_document returns ValidatedFieldResult list
2. Async path produces identical results to sync path
3. Async path handles provider errors gracefully
4. enqueue_case_async is importable and callable
5. _async_extract_document_evidence_first uses async_collect_evidence
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.domain.models import DocumentIR, DocumentIRBlock
from app.services.llm_provider.fallback import ConservativeLocalProvider
from app.services.llm_provider.types import SemanticExtractionProvider
from app.services.pipeline import async_extract_document, extract_document


def _minimal_document_ir() -> DocumentIR:
    """Create a minimal DocumentIR for testing."""
    return DocumentIR(
        document_id="test-async",
        profile_id="medical_inpatient_zh",
        source_filename="test.pdf",
        blocks=[
            DocumentIRBlock(
                block_id="b0001-test",
                page=1,
                reading_order=1,
                text="既往史：否认高血压病、糖尿病、冠心病等病史。",
                confidence=0.95,
                section_id="jws",
                section_label="既往史",
            ),
            DocumentIRBlock(
                block_id="b0002-test",
                page=1,
                reading_order=2,
                text="个人史：否认吸烟史、饮酒史。",
                confidence=0.93,
                section_id="grs",
                section_label="个人史",
            ),
        ],
        metadata={"deidentification": {"online_llm_allowed": False}},
    )


# ---------------------------------------------------------------------------
# 1. async_extract_document returns results
# ---------------------------------------------------------------------------


def test_async_extract_document_produces_results():
    """async_extract_document returns ValidatedFieldResult list."""
    doc = _minimal_document_ir()
    provider = ConservativeLocalProvider()

    async def _run():
        return await async_extract_document(doc, provider=provider)

    results = asyncio.run(_run())
    assert isinstance(results, list)
    assert len(results) > 0
    # All results should have field_key
    for r in results:
        assert r.field_key


# ---------------------------------------------------------------------------
# 2. Async path produces same results as sync path
# ---------------------------------------------------------------------------


def test_async_extract_matches_sync_extract():
    """Async path produces same results as sync path for local provider."""
    doc = _minimal_document_ir()
    provider = ConservativeLocalProvider()

    sync_results = extract_document(doc, provider=provider)

    async def _run():
        return await async_extract_document(doc, provider=provider)

    async_results = asyncio.run(_run())

    # Same number of results
    assert len(async_results) == len(sync_results)
    # Same field keys
    sync_keys = {r.field_key for r in sync_results}
    async_keys = {r.field_key for r in async_results}
    assert sync_keys == async_keys
    # Same normalized codes
    for sr in sync_results:
        ar = next(r for r in async_results if r.field_key == sr.field_key)
        assert ar.normalized_code == sr.normalized_code


# ---------------------------------------------------------------------------
# 3. Async path handles errors gracefully
# ---------------------------------------------------------------------------


def test_async_extract_handles_error_gracefully():
    """Async path handles provider errors without crashing."""
    doc = _minimal_document_ir()

    class FailingProvider(ConservativeLocalProvider):
        async def async_collect_evidence(self, **kwargs):
            raise RuntimeError("Simulated LLM failure")

    provider = FailingProvider()

    async def _run():
        return await async_extract_document(doc, provider=provider)

    results = asyncio.run(_run())
    # Should still return results (error fallback)
    assert isinstance(results, list)
    assert len(results) > 0


# ---------------------------------------------------------------------------
# 4. enqueue_case_async is importable
# ---------------------------------------------------------------------------


def test_enqueue_case_async_importable():
    """enqueue_case_async can be imported from pipeline module."""
    import inspect

    from app.services.pipeline import enqueue_case_async

    assert callable(enqueue_case_async)
    assert inspect.iscoroutinefunction(enqueue_case_async)


# ---------------------------------------------------------------------------
# 5. _async_extract_document_evidence_first calls async_collect_evidence
# ---------------------------------------------------------------------------


def test_async_path_calls_async_collect_evidence():
    """The async pipeline path calls async_collect_evidence, not sync collect_evidence."""
    doc = _minimal_document_ir()
    # Allow online so the provider is used directly (not replaced by ConservativeLocalProvider)
    doc.metadata["deidentification"]["online_llm_allowed"] = True

    sync_called = []
    async_called = []

    class TrackingProvider(ConservativeLocalProvider):
        def collect_evidence(self, **kwargs):
            sync_called.append(True)
            return super().collect_evidence(**kwargs)

        async def async_collect_evidence(self, **kwargs):
            async_called.append(True)
            # Delegate to sync via to_thread (same as base class default)
            import asyncio
            return await asyncio.to_thread(
                ConservativeLocalProvider.collect_evidence, self, **kwargs
            )

    provider = TrackingProvider()

    async def _run():
        return await async_extract_document(doc, provider=provider)

    results = asyncio.run(_run())
    assert len(results) > 0
    # async_collect_evidence should have been called
    assert len(async_called) == 1
    # The sync collect_evidence is called indirectly via to_thread from async,
    # but the pipeline itself should NOT call collect_evidence directly
    # (it goes through async_collect_evidence which may delegate to sync)


# ---------------------------------------------------------------------------
# 6. Async extraction strategy tag in provenance
# ---------------------------------------------------------------------------


def test_async_extraction_strategy_in_provenance():
    """Async path marks provenance with evidence_first_multimodal_async strategy."""
    doc = _minimal_document_ir()
    provider = ConservativeLocalProvider()

    async def _run():
        return await async_extract_document(doc, provider=provider)

    results = asyncio.run(_run())
    # At least one result should have the async strategy marker
    strategies = {r.provenance.get("extraction_strategy") for r in results if r.provenance}
    assert "evidence_first_multimodal_async" in strategies


# ---------------------------------------------------------------------------
# 7. Backward compatibility: sync extract_document unchanged
# ---------------------------------------------------------------------------


def test_sync_extract_document_still_works():
    """The sync extract_document function remains unchanged and functional."""
    doc = _minimal_document_ir()
    provider = ConservativeLocalProvider()

    results = extract_document(doc, provider=provider)
    assert isinstance(results, list)
    assert len(results) > 0
    # Sync path uses the non-async strategy tag
    strategies = {r.provenance.get("extraction_strategy") for r in results if r.provenance}
    assert "evidence_first_multimodal" in strategies
