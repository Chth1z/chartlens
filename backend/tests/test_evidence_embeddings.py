"""Tests for embedding-based evidence scoring."""
from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from app.domain.models import DocumentIRBlock, FieldDefinition, LlmFieldConfig
from app.services.evidence_embeddings import (
    _cosine_similarity,
    _field_query_text,
    clear_embedding_cache,
    compute_block_embeddings,
    compute_field_embedding,
    embeddings_enabled,
    semantic_scores,
    _embedding_cache,
)


def _block(block_id: str, text: str) -> DocumentIRBlock:
    return DocumentIRBlock(
        block_id=block_id, page=1, reading_order=1, text=text, confidence=0.9
    )


def _field(
    key: str = "test_field",
    label: str = "高血压",
    synonyms: list[str] | None = None,
) -> FieldDefinition:
    return FieldDefinition(
        key=key,
        field_group_key="test_group",
        label=label,
        export_header="Test",
        synonyms=synonyms or ["血压高", "hypertension"],
        llm=LlmFieldConfig(),
    )


class TestCosineSimlarity:
    def test_identical_vectors(self):
        a = np.array([1.0, 0.0, 0.0])
        assert _cosine_similarity(a, a) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 1.0, 0.0])
        assert _cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        a = np.array([1.0, 0.0])
        b = np.array([-1.0, 0.0])
        assert _cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_zero_vector(self):
        a = np.array([0.0, 0.0])
        b = np.array([1.0, 1.0])
        assert _cosine_similarity(a, b) == 0.0

    def test_similar_vectors(self):
        a = np.array([0.9, 0.1, 0.0])
        b = np.array([0.85, 0.15, 0.0])
        sim = _cosine_similarity(a, b)
        assert sim > 0.99  # Very similar vectors


class TestFieldQueryText:
    def test_includes_label_and_synonyms(self):
        field = _field(label="高血压", synonyms=["血压高", "hypertension"])
        text = _field_query_text(field)
        assert "高血压" in text
        assert "血压高" in text
        assert "hypertension" in text

    def test_limits_synonyms(self):
        field = _field(synonyms=["s1", "s2", "s3", "s4", "s5", "s6", "s7"])
        text = _field_query_text(field)
        # Only first 5 synonyms included
        assert "s5" in text
        assert "s6" not in text

    def test_empty_label(self):
        field = FieldDefinition(
            key="empty",
            field_group_key="test_group",
            label="",
            export_header="Test",
            synonyms=[],
            negation_terms=[],
            llm=LlmFieldConfig(),
        )
        text = _field_query_text(field)
        assert text == ""


class TestEmbeddingsEnabled:
    def test_disabled_by_default(self):
        with patch("app.services.evidence_embeddings.settings") as mock_settings:
            mock_settings.evidence_embeddings = False
            assert not embeddings_enabled()

    def test_enabled_when_setting_true(self):
        with patch("app.services.evidence_embeddings.settings") as mock_settings:
            mock_settings.evidence_embeddings = True
            assert embeddings_enabled()


class TestComputeBlockEmbeddings:
    def test_returns_none_when_disabled(self):
        blocks = [_block("b1", "test text")]
        with patch("app.services.evidence_embeddings.embeddings_enabled", return_value=False):
            result = compute_block_embeddings(blocks)
        assert result is None

    def test_returns_none_on_empty_blocks(self):
        with patch("app.services.evidence_embeddings.embeddings_enabled", return_value=True):
            result = compute_block_embeddings([])
        assert result is None

    def test_returns_none_on_api_failure(self):
        blocks = [_block("b1", "test text")]
        with patch("app.services.evidence_embeddings.embeddings_enabled", return_value=True):
            with patch(
                "app.services.evidence_embeddings._call_embedding_api",
                side_effect=RuntimeError("no key"),
            ):
                result = compute_block_embeddings(blocks)
        assert result is None

    def test_caches_by_signature(self):
        blocks = [_block("b1", "test text")]
        vec = np.array([1.0, 0.0], dtype=np.float32)

        with patch("app.services.evidence_embeddings.embeddings_enabled", return_value=True):
            with patch(
                "app.services.evidence_embeddings._call_embedding_api",
                return_value=[vec],
            ) as mock_api:
                result1 = compute_block_embeddings(blocks, cache_signature="sig1")
                result2 = compute_block_embeddings(blocks, cache_signature="sig1")

        # API called only once due to caching
        assert mock_api.call_count == 1
        assert result1 is not None
        assert result2 is not None
        assert np.array_equal(result1["b1"], result2["b1"])

        # Cleanup
        clear_embedding_cache()

    def test_cache_eviction(self):
        """Cache evicts oldest entry when full."""
        from app.services.evidence_embeddings import _MAX_CACHE_ENTRIES

        # Fill cache to max
        for i in range(_MAX_CACHE_ENTRIES):
            _embedding_cache[f"sig_{i}"] = {"b": np.array([float(i)])}

        blocks = [_block("b1", "new")]
        vec = np.array([9.0], dtype=np.float32)

        with patch("app.services.evidence_embeddings.embeddings_enabled", return_value=True):
            with patch(
                "app.services.evidence_embeddings._call_embedding_api",
                return_value=[vec],
            ):
                compute_block_embeddings(blocks, cache_signature="new_sig")

        # Oldest entry evicted, new one present
        assert "sig_0" not in _embedding_cache
        assert "new_sig" in _embedding_cache

        clear_embedding_cache()


class TestComputeFieldEmbedding:
    def test_returns_none_when_disabled(self):
        with patch("app.services.evidence_embeddings.embeddings_enabled", return_value=False):
            result = compute_field_embedding(_field())
        assert result is None

    def test_returns_none_on_api_failure(self):
        with patch("app.services.evidence_embeddings.embeddings_enabled", return_value=True):
            with patch(
                "app.services.evidence_embeddings._call_embedding_api",
                side_effect=RuntimeError("network error"),
            ):
                result = compute_field_embedding(_field())
        assert result is None

    def test_returns_vector_on_success(self):
        vec = np.array([0.5, 0.5], dtype=np.float32)
        with patch("app.services.evidence_embeddings.embeddings_enabled", return_value=True):
            with patch(
                "app.services.evidence_embeddings._call_embedding_api",
                return_value=[vec],
            ):
                result = compute_field_embedding(_field())
        assert result is not None
        assert np.array_equal(result, vec)


class TestSemanticScores:
    def test_returns_empty_when_disabled(self):
        with patch("app.services.evidence_embeddings.embeddings_enabled", return_value=False):
            blocks = [_block("b1", "高血压病史")]
            field = _field()
            scores = semantic_scores(blocks, field)
            assert scores == {}

    def test_returns_scores_with_precomputed_embeddings(self):
        blocks = [
            _block("b1", "既往史：高血压病10年"),
            _block("b2", "手术记录：阑尾切除术"),
        ]
        field = _field(label="高血压", synonyms=["血压高"])

        # b1 is similar to field, b2 is not
        block_embeddings = {
            "b1": np.array([0.9, 0.1, 0.0, 0.0], dtype=np.float32),
            "b2": np.array([0.0, 0.0, 0.9, 0.1], dtype=np.float32),
        }
        field_embedding = np.array([0.85, 0.15, 0.0, 0.0], dtype=np.float32)

        with patch("app.services.evidence_embeddings.embeddings_enabled", return_value=True):
            with patch(
                "app.services.evidence_embeddings.compute_field_embedding",
                return_value=field_embedding,
            ):
                scores = semantic_scores(
                    blocks, field, block_embeddings=block_embeddings
                )

        # b1 should have high similarity
        assert "b1" in scores
        assert scores["b1"] > 0.9
        # b2 should be filtered out (< 0.3 threshold)
        assert "b2" not in scores

    def test_returns_empty_when_field_embedding_fails(self):
        blocks = [_block("b1", "text")]
        block_embeddings = {
            "b1": np.array([1.0, 0.0], dtype=np.float32),
        }

        with patch("app.services.evidence_embeddings.embeddings_enabled", return_value=True):
            with patch(
                "app.services.evidence_embeddings.compute_field_embedding",
                return_value=None,
            ):
                scores = semantic_scores(
                    blocks, _field(), block_embeddings=block_embeddings
                )

        assert scores == {}

    def test_returns_empty_when_block_embeddings_unavailable(self):
        blocks = [_block("b1", "text")]

        with patch("app.services.evidence_embeddings.embeddings_enabled", return_value=True):
            with patch(
                "app.services.evidence_embeddings.compute_block_embeddings",
                return_value=None,
            ):
                scores = semantic_scores(blocks, _field())

        assert scores == {}


class TestEmbeddingCache:
    def test_clear_cache(self):
        _embedding_cache["test_sig"] = {"b1": np.array([1.0])}
        clear_embedding_cache()
        assert len(_embedding_cache) == 0


class TestIntegrationWithEvidence:
    """Test that embedding scores integrate correctly with build_evidence_packs."""

    def test_embedding_disabled_no_change(self):
        """When embeddings disabled, build_evidence_packs works as before."""
        from app.services.evidence import build_evidence_packs

        blocks = [
            DocumentIRBlock(
                block_id="b1",
                page=1,
                reading_order=1,
                text="既往史：高血压病10年",
                section_label="既往史",
                confidence=0.95,
            ),
        ]
        field = _field(label="高血压", synonyms=["血压高"])

        with patch("app.services.evidence_embeddings.settings") as mock_settings:
            mock_settings.evidence_embeddings = False
            packs = build_evidence_packs(None, field, blocks=blocks)

        # Should still find the block via term matching
        assert len(packs) >= 1
        assert "embedding_similarity" not in (packs[0].score_reason or "")

    def test_embedding_enabled_adds_score(self):
        """When embeddings enabled and API works, score includes embedding bonus."""
        from app.services.evidence import build_evidence_packs

        blocks = [
            DocumentIRBlock(
                block_id="b1",
                page=1,
                reading_order=1,
                text="既往史：高血压病10年",
                section_label="既往史",
                confidence=0.95,
            ),
            DocumentIRBlock(
                block_id="b2",
                page=1,
                reading_order=2,
                text="手术记录：阑尾切除术",
                section_label="手术记录",
                confidence=0.95,
            ),
        ]
        field = _field(label="高血压", synonyms=["血压高"])

        mock_scores = {"b1": 0.92}

        with patch(
            "app.services.evidence_embeddings.embeddings_enabled", return_value=True
        ):
            with patch(
                "app.services.evidence_embeddings.semantic_scores", return_value=mock_scores
            ) as mock_sem:
                packs = build_evidence_packs(None, field, blocks=blocks)

        # b1 should have embedding_similarity in its score_reason
        b1_pack = next((p for p in packs if p.block_id == "b1"), None)
        assert b1_pack is not None
        assert "embedding_similarity" in (b1_pack.score_reason or "")
