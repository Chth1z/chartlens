"""Tests for evidence_reranker module."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.domain.models import DocumentIRBlock, FieldDefinition, LlmFieldConfig
from app.services.evidence_reranker import (
    _build_query,
    rerank_candidates,
    reranking_enabled,
)


def _make_block(block_id: str, text: str, reading_order: int = 1) -> DocumentIRBlock:
    return DocumentIRBlock(
        block_id=block_id,
        page=1,
        reading_order=reading_order,
        text=text,
    )


def _make_field(
    key: str = "test_field",
    label: str = "Test Field",
    synonyms: list[str] | None = None,
) -> FieldDefinition:
    return FieldDefinition(
        key=key,
        field_group_key="test_group",
        label=label,
        export_header="Test",
        synonyms=synonyms or [],
        llm=LlmFieldConfig(),
    )


class TestRerankingEnabled:
    def test_disabled_by_default(self):
        with patch("app.services.evidence_reranker.settings") as mock_settings:
            mock_settings.evidence_reranking = False
            assert reranking_enabled() is False

    def test_enabled_when_setting_true(self):
        with patch("app.services.evidence_reranker.settings") as mock_settings:
            mock_settings.evidence_reranking = True
            assert reranking_enabled() is True

    def test_fallback_when_attribute_missing(self):
        with patch("app.services.evidence_reranker.settings", spec=[]):
            # When the attribute doesn't exist, getattr with default returns False
            assert reranking_enabled() is False


class TestBuildQuery:
    def test_label_only(self):
        field = _make_field(label="血压")
        assert _build_query(field) == "血压"

    def test_label_with_synonyms(self):
        field = _make_field(label="血压", synonyms=["BP", "blood pressure", "收缩压"])
        assert _build_query(field) == "血压 BP blood pressure 收缩压"

    def test_synonyms_limited_to_three(self):
        field = _make_field(
            label="血压",
            synonyms=["syn1", "syn2", "syn3", "syn4", "syn5"],
        )
        result = _build_query(field)
        assert result == "血压 syn1 syn2 syn3"
        assert "syn4" not in result


class TestRerankCandidates:
    def test_returns_unchanged_when_disabled(self):
        with patch("app.services.evidence_reranker.reranking_enabled", return_value=False):
            block_a = _make_block("a", "text a")
            block_b = _make_block("b", "text b")
            candidates = [
                (block_a, 5.0, ["term"], ["reason"]),
                (block_b, 3.0, ["term2"], ["reason2"]),
            ]
            result = rerank_candidates(_make_field(), candidates)
            assert result is candidates

    def test_returns_unchanged_when_single_candidate(self):
        with patch("app.services.evidence_reranker.reranking_enabled", return_value=True):
            block_a = _make_block("a", "text a")
            candidates = [(block_a, 5.0, ["term"], ["reason"])]
            result = rerank_candidates(_make_field(), candidates)
            assert result is candidates

    def test_returns_unchanged_when_empty(self):
        with patch("app.services.evidence_reranker.reranking_enabled", return_value=True):
            result = rerank_candidates(_make_field(), [])
            assert result == []

    def test_reorders_based_on_scores(self):
        with patch("app.services.evidence_reranker.reranking_enabled", return_value=True), \
             patch("app.services.evidence_reranker.settings") as mock_settings, \
             patch("app.services.evidence_reranker._score_pairs") as mock_score:
            mock_settings.evidence_reranking_top_k = 8
            # Block B gets higher rerank score despite lower original score
            mock_score.return_value = [1.0, 5.0, 2.0]

            block_a = _make_block("a", "text a")
            block_b = _make_block("b", "text b")
            block_c = _make_block("c", "text c")
            candidates = [
                (block_a, 10.0, ["t1"], ["r1"]),
                (block_b, 5.0, ["t2"], ["r2"]),
                (block_c, 3.0, ["t3"], ["r3"]),
            ]

            result = rerank_candidates(_make_field(), candidates)

            # Block B should be first (highest rerank score)
            assert result[0][0].block_id == "b"
            # Verify reranked reason is appended
            assert any("reranked:" in r for r in result[0][3])

    def test_handles_api_failure_gracefully(self):
        with patch("app.services.evidence_reranker.reranking_enabled", return_value=True), \
             patch("app.services.evidence_reranker.settings") as mock_settings, \
             patch("app.services.evidence_reranker._score_pairs") as mock_score:
            mock_settings.evidence_reranking_top_k = 8
            mock_score.side_effect = RuntimeError("API unavailable")

            block_a = _make_block("a", "text a")
            block_b = _make_block("b", "text b")
            candidates = [
                (block_a, 5.0, ["t1"], ["r1"]),
                (block_b, 3.0, ["t2"], ["r2"]),
            ]

            result = rerank_candidates(_make_field(), candidates)
            # Returns original unchanged
            assert result is candidates

    def test_handles_score_count_mismatch(self):
        with patch("app.services.evidence_reranker.reranking_enabled", return_value=True), \
             patch("app.services.evidence_reranker.settings") as mock_settings, \
             patch("app.services.evidence_reranker._score_pairs") as mock_score:
            mock_settings.evidence_reranking_top_k = 8
            # Return wrong number of scores
            mock_score.return_value = [3.0]

            block_a = _make_block("a", "text a")
            block_b = _make_block("b", "text b")
            candidates = [
                (block_a, 5.0, ["t1"], ["r1"]),
                (block_b, 3.0, ["t2"], ["r2"]),
            ]

            result = rerank_candidates(_make_field(), candidates)
            assert result is candidates

    def test_respects_top_k_setting(self):
        with patch("app.services.evidence_reranker.reranking_enabled", return_value=True), \
             patch("app.services.evidence_reranker.settings") as mock_settings, \
             patch("app.services.evidence_reranker._score_pairs") as mock_score:
            mock_settings.evidence_reranking_top_k = 2
            # Only first 2 candidates get reranked
            mock_score.return_value = [1.0, 4.0]

            blocks = [_make_block(f"b{i}", f"text {i}") for i in range(4)]
            candidates = [
                (blocks[0], 10.0, [], ["r"]),
                (blocks[1], 8.0, [], ["r"]),
                (blocks[2], 6.0, [], ["r"]),
                (blocks[3], 4.0, [], ["r"]),
            ]

            result = rerank_candidates(_make_field(), candidates)

            # First 2 are reranked, last 2 stay in original order
            assert result[2][0].block_id == "b2"
            assert result[3][0].block_id == "b3"
            # Block b1 should be promoted (higher rerank score)
            assert result[0][0].block_id == "b1"

    def test_blended_score_calculation(self):
        with patch("app.services.evidence_reranker.reranking_enabled", return_value=True), \
             patch("app.services.evidence_reranker.settings") as mock_settings, \
             patch("app.services.evidence_reranker._score_pairs") as mock_score:
            mock_settings.evidence_reranking_top_k = 8
            mock_score.return_value = [3.0, 3.0]

            block_a = _make_block("a", "text a")
            block_b = _make_block("b", "text b")
            candidates = [
                (block_a, 10.0, [], []),
                (block_b, 5.0, [], []),
            ]

            result = rerank_candidates(_make_field(), candidates)

            # block_a: 0.6 * 3.0 + 0.4 * (10/10) * 5.0 = 1.8 + 2.0 = 3.8
            # block_b: 0.6 * 3.0 + 0.4 * (5/10) * 5.0 = 1.8 + 1.0 = 2.8
            assert abs(result[0][1] - 3.8) < 0.01
            assert abs(result[1][1] - 2.8) < 0.01


class TestIntegrationWithEvidence:
    """Test that reranking integrates correctly with build_evidence_packs."""

    def test_build_evidence_packs_calls_reranker_when_enabled(self):
        from app.domain.models import DocumentIR
        from app.services.evidence import build_evidence_packs

        blocks = [
            _make_block("b1", "血压 120/80", reading_order=1),
            _make_block("b2", "体温 36.5", reading_order=2),
            _make_block("b3", "血压偏高", reading_order=3),
        ]
        doc_ir = DocumentIR(
            document_id="test",
            profile_id="test",
            source_filename="test.pdf",
            blocks=blocks,
        )
        field = _make_field(label="血压", synonyms=["BP"])

        with patch("app.services.evidence_reranker.reranking_enabled", return_value=True), \
             patch("app.services.evidence_reranker.settings") as mock_settings, \
             patch("app.services.evidence_reranker._score_pairs") as mock_score, \
             patch("app.services.evidence_embeddings.embeddings_enabled", return_value=False):
            mock_settings.evidence_reranking_top_k = 8
            # Give block b3 highest rerank score
            mock_score.return_value = [2.0, 5.0]

            packs = build_evidence_packs(doc_ir, field)

            # Reranker was called
            mock_score.assert_called_once()
            # b3 should be ranked first due to high rerank score
            assert packs[0].block_id == "b3"

    def test_build_evidence_packs_skips_reranker_when_disabled(self):
        from app.domain.models import DocumentIR
        from app.services.evidence import build_evidence_packs

        blocks = [
            _make_block("b1", "血压 120/80", reading_order=1),
            _make_block("b2", "血压偏高", reading_order=2),
        ]
        doc_ir = DocumentIR(
            document_id="test",
            profile_id="test",
            source_filename="test.pdf",
            blocks=blocks,
        )
        field = _make_field(label="血压", synonyms=["BP"])

        with patch("app.services.evidence_reranker.reranking_enabled", return_value=False), \
             patch("app.services.evidence_reranker._score_pairs") as mock_score, \
             patch("app.services.evidence_embeddings.embeddings_enabled", return_value=False):
            packs = build_evidence_packs(doc_ir, field)

            # Reranker was NOT called
            mock_score.assert_not_called()
            # Packs still returned normally
            assert len(packs) >= 1
