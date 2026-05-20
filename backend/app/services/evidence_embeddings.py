"""Embedding-based semantic scoring for evidence retrieval.

Opt-in via EYEX_EVIDENCE_EMBEDDINGS=true. Uses OpenAI text-embedding-3-small
to compute embeddings for document blocks and field queries, then adds
cosine similarity scores to the existing FTS5 + keyword scoring.

Embeddings are cached in-memory per case (keyed by block_ids_signature)
to avoid redundant API calls within a single case processing run.
"""
from __future__ import annotations

import logging

import numpy as np

from app.core.settings import settings
from app.domain.models import DocumentIRBlock, FieldDefinition

logger = logging.getLogger(__name__)

# In-memory cache: signature -> block_id -> embedding vector
_embedding_cache: dict[str, dict[str, np.ndarray]] = {}
_MAX_CACHE_ENTRIES = 32


def embeddings_enabled() -> bool:
    """Check if embedding-based evidence scoring is enabled."""
    return getattr(settings, "evidence_embeddings", False)


def compute_block_embeddings(
    blocks: list[DocumentIRBlock],
    *,
    cache_signature: str | None = None,
) -> dict[str, np.ndarray] | None:
    """Compute embeddings for all blocks. Returns block_id -> vector dict.

    Returns None if embeddings are disabled or unavailable.
    Uses cache_signature (from EvidenceIndex.block_ids_signature) for caching.
    """
    if not embeddings_enabled():
        return None

    # Check cache
    if cache_signature and cache_signature in _embedding_cache:
        return _embedding_cache[cache_signature]

    texts = [block.text.strip() for block in blocks]
    if not texts:
        return None

    try:
        vectors = _call_embedding_api(texts)
    except Exception as exc:
        logger.warning(
            "Embedding API call failed, falling back to non-embedding scoring: %s",
            exc,
        )
        return None

    result = {block.block_id: vec for block, vec in zip(blocks, vectors)}

    # Cache with LRU eviction
    if cache_signature:
        if len(_embedding_cache) >= _MAX_CACHE_ENTRIES:
            oldest_key = next(iter(_embedding_cache))
            del _embedding_cache[oldest_key]
        _embedding_cache[cache_signature] = result

    return result


def compute_field_embedding(field: FieldDefinition) -> np.ndarray | None:
    """Compute embedding for a field's query terms."""
    if not embeddings_enabled():
        return None

    query_text = _field_query_text(field)
    if not query_text:
        return None

    try:
        vectors = _call_embedding_api([query_text])
        return vectors[0] if vectors else None
    except Exception as exc:
        logger.warning("Field embedding failed for %s: %s", field.key, exc)
        return None


def semantic_scores(
    blocks: list[DocumentIRBlock],
    field: FieldDefinition,
    *,
    block_embeddings: dict[str, np.ndarray] | None = None,
    cache_signature: str | None = None,
) -> dict[str, float]:
    """Compute semantic similarity scores for blocks against a field.

    Returns block_id -> similarity_score (0.0 to 1.0).
    Returns empty dict if embeddings are unavailable.
    """
    if not embeddings_enabled():
        return {}

    if block_embeddings is None:
        block_embeddings = compute_block_embeddings(
            blocks, cache_signature=cache_signature
        )
    if block_embeddings is None:
        return {}

    field_vec = compute_field_embedding(field)
    if field_vec is None:
        return {}

    scores: dict[str, float] = {}
    for block_id, block_vec in block_embeddings.items():
        sim = _cosine_similarity(field_vec, block_vec)
        if sim > 0.3:  # Only include meaningful similarities
            scores[block_id] = float(sim)

    return scores


def _field_query_text(field: FieldDefinition) -> str:
    """Build a query string from field metadata for embedding."""
    parts = [field.label]
    parts.extend(field.synonyms[:5])  # Limit to avoid too-long queries
    parts.extend(field.negation_terms[:3])
    return " ".join(part for part in parts if part)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def _call_embedding_api(texts: list[str]) -> list[np.ndarray]:
    """Call OpenAI embedding API. Raises on failure."""
    from openai import OpenAI

    api_key = settings.openai_api_key
    if not api_key:
        raise RuntimeError("EYEX_OPENAI_API_KEY required for embeddings")

    client = OpenAI(api_key=api_key, timeout=30.0)

    # Truncate texts to avoid token limits (8191 tokens for text-embedding-3-small)
    truncated = [text[:2000] for text in texts]

    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=truncated,
        dimensions=256,  # Use smaller dimensions for efficiency
    )

    return [np.array(item.embedding, dtype=np.float32) for item in response.data]


def clear_embedding_cache() -> None:
    """Clear the in-memory embedding cache."""
    _embedding_cache.clear()
