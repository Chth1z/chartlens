"""Cross-encoder reranking for evidence candidates.

After initial retrieval (BM25 + embedding), rescores the top-K candidates
using an LLM-based relevance judgment. This improves precision by promoting
truly relevant evidence above superficially matching blocks.

Opt-in via EYEX_EVIDENCE_RERANKING=true. Uses OpenAI API for scoring.
"""
from __future__ import annotations

import logging

from app.core.settings import settings
from app.domain.models import DocumentIRBlock, FieldDefinition

logger = logging.getLogger(__name__)


def reranking_enabled() -> bool:
    """Check if evidence reranking is enabled."""
    return getattr(settings, "evidence_reranking", False)


def rerank_candidates(
    field: FieldDefinition,
    candidates: list[tuple[DocumentIRBlock, float, list[str], list[str]]],
) -> list[tuple[DocumentIRBlock, float, list[str], list[str]]]:
    """Rerank evidence candidates using cross-encoder relevance scoring.

    Takes the top-K scored candidates and rescores them based on
    semantic relevance to the field query. Returns candidates in
    new order with updated scores.

    Returns candidates unchanged if:
    - Reranking is disabled
    - API call fails
    - Less than 2 candidates (nothing to rerank)
    """
    if not reranking_enabled():
        return candidates

    if len(candidates) < 2:
        return candidates

    top_k = min(len(candidates), settings.evidence_reranking_top_k)
    to_rerank = candidates[:top_k]
    rest = candidates[top_k:]

    query = _build_query(field)
    documents = [block.text for block, _, _, _ in to_rerank]

    try:
        scores = _score_pairs(query, documents)
    except Exception as exc:
        logger.warning("Evidence reranking failed for field %s: %s", field.key, exc)
        return candidates

    if not scores or len(scores) != len(to_rerank):
        return candidates

    # Combine original score with reranking score
    max_orig = max(s for _, s, _, _ in to_rerank) or 1.0
    reranked = []
    for (block, orig_score, match_terms, reasons), rerank_score in zip(to_rerank, scores):
        # Blend: 60% rerank score (0-5 range) + 40% original score (normalized)
        blended = 0.6 * rerank_score + 0.4 * (orig_score / max_orig) * 5.0
        new_reasons = [*reasons, f"reranked:{rerank_score:.2f}"]
        reranked.append((block, blended, match_terms, new_reasons))

    # Sort reranked by new score
    reranked.sort(key=lambda item: item[1], reverse=True)

    return reranked + rest


def _build_query(field: FieldDefinition) -> str:
    """Build the query string for reranking."""
    parts = [field.label]
    parts.extend(field.synonyms[:3])
    return " ".join(part for part in parts if part)


def _score_pairs(query: str, documents: list[str]) -> list[float]:
    """Score query-document pairs using OpenAI API.

    Asks the model to rate relevance of each document to the query
    on a 0-5 scale. Returns list of scores.
    """
    from openai import OpenAI

    api_key = settings.openai_api_key
    if not api_key:
        raise RuntimeError("EYEX_OPENAI_API_KEY required for reranking")

    client = OpenAI(api_key=api_key, timeout=30.0)

    # Build a single prompt that scores all documents at once
    doc_list = "\n".join(
        f"[{i}] {doc[:200]}" for i, doc in enumerate(documents)
    )

    prompt = (
        f"Rate the relevance of each document to the query on a scale of 0-5.\n"
        f"Query: {query}\n\n"
        f"Documents:\n{doc_list}\n\n"
        f"Return a JSON array of numbers (one score per document, in order). "
        f"Example: [4.2, 1.0, 3.5]\n"
        f"Only output the JSON array, nothing else."
    )

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=100,
    )

    content = response.choices[0].message.content or ""
    import json_repair
    scores = json_repair.loads(content)

    if not isinstance(scores, list):
        raise ValueError(f"Expected list, got {type(scores)}")

    return [float(s) for s in scores[: len(documents)]]
