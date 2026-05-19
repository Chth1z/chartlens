from __future__ import annotations

import hashlib
import math
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field as dataclass_field
from typing import Iterator

from app.domain.models import DocumentIR, DocumentIRBlock, EvidenceCandidate, EvidencePack, FieldDefinition, FieldGroup


NEGATION_MARKERS = ("否认", "无", "未见", "未发现", "不伴", "未诉", "不吸烟", "不饮酒")
UNCERTAIN_MARKERS = ("？", "?", "疑似", "待排", "可能", "考虑", "倾向")
FAMILY_MARKERS = ("家族史", "父", "母", "兄", "姐", "弟", "妹", "子", "女")
DEFAULT_GROUP_EVIDENCE_BUDGET = 3200


@dataclass
class EvidenceIndex:
    """Reusable FTS5 + block-by-id map over a stable list of blocks.

    Built once per case (or per group, if the caller scopes blocks).
    `_fts_scores_with_index` and `build_evidence_packs` accept an
    optional ``EvidenceIndex``; when provided, the FTS table is reused
    instead of rebuilt per field.

    Cache key invariant: an ``EvidenceIndex`` is only valid for the
    exact ``blocks`` list it was constructed from. If a caller passes a
    different ``blocks`` argument to ``build_evidence_packs`` while
    reusing the index, behavior is undefined; the caller is responsible
    for keeping the block set in sync.
    """

    blocks: tuple[DocumentIRBlock, ...]
    block_by_id: dict[str, DocumentIRBlock]
    connection: sqlite3.Connection | None
    block_ids_signature: str
    _closed: bool = dataclass_field(default=False, repr=False)

    def close(self) -> None:
        """Release the in-memory FTS connection. Idempotent."""
        if self._closed:
            return
        self._closed = True
        if self.connection is not None:
            try:
                self.connection.close()
            except Exception:
                pass
            self.connection = None


def build_evidence_index(blocks: list[DocumentIRBlock]) -> EvidenceIndex:
    """Construct an ``EvidenceIndex`` once for the given blocks.

    Creates an in-memory SQLite FTS5 connection, populates the
    ``block_fts`` virtual table with one row per block, and returns the
    index. Callers must call ``close()`` when done (or use the
    :func:`evidence_index` context manager).

    If FTS5 is unavailable (very old SQLite builds), the connection
    field is set to ``None``; the indexed code path then degrades to
    "no FTS scores" without raising. This mirrors the legacy
    ``_fts_scores`` ``except Exception`` fallback.
    """

    block_tuple = tuple(blocks)
    block_by_id = {block.block_id: block for block in block_tuple}
    signature = hashlib.sha1(
        "|".join(block.block_id for block in block_tuple).encode("utf-8")
    ).hexdigest()
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(":memory:")
        connection.execute(
            "CREATE VIRTUAL TABLE block_fts USING fts5(block_id UNINDEXED, text)"
        )
        connection.executemany(
            "INSERT INTO block_fts(block_id, text) VALUES (?, ?)",
            [(block.block_id, block.text) for block in block_tuple],
        )
    except Exception:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
        connection = None
    return EvidenceIndex(
        blocks=block_tuple,
        block_by_id=block_by_id,
        connection=connection,
        block_ids_signature=signature,
    )


@contextmanager
def evidence_index(blocks: list[DocumentIRBlock]) -> Iterator[EvidenceIndex]:
    """Yield an ``EvidenceIndex`` and close it on exit."""
    index = build_evidence_index(blocks)
    try:
        yield index
    finally:
        index.close()


def blocks_for_group(document_ir: DocumentIR, group: FieldGroup) -> list[DocumentIRBlock]:
    if not group.source_sections:
        return document_ir.blocks
    selected = [block for block in document_ir.blocks if block.section_label in group.source_sections]
    return selected or document_ir.blocks


def evidence_for_field(
    document_ir: DocumentIR | None,
    field: FieldDefinition,
    *,
    blocks: list[DocumentIRBlock] | None = None,
    index: EvidenceIndex | None = None,
) -> list[EvidenceCandidate]:
    return [
        EvidenceCandidate(
            block_id=pack.block_id,
            text=pack.text,
            page=pack.page,
            bbox=pack.bbox,
            section_label=pack.section_label,
            document_kind=pack.document_kind,
            ocr_confidence=pack.ocr_confidence,
            score=pack.score,
            match_terms=pack.match_terms,
            score_reason=pack.score_reason,
            pack_hash=pack.pack_hash,
            context_text=pack.context_text,
            token_estimate=pack.token_estimate,
            negated=pack.negated,
            uncertain=pack.uncertain,
            family_context=pack.family_context,
            rank=pack.rank,
        )
        for pack in build_evidence_packs(document_ir, field, blocks=blocks, index=index)
    ]


def build_evidence_packs(
    document_ir: DocumentIR | None,
    field: FieldDefinition,
    *,
    blocks: list[DocumentIRBlock] | None = None,
    group_budget: int | None = None,
    index: EvidenceIndex | None = None,
) -> list[EvidencePack]:
    if index is not None:
        source_blocks = list(index.blocks) if blocks is None else blocks
        block_by_id = (
            index.block_by_id
            if blocks is None
            else {block.block_id: block for block in source_blocks}
        )
    else:
        source_blocks = blocks if blocks is not None else document_ir.blocks if document_ir is not None else []
        block_by_id = {block.block_id: block for block in source_blocks}
    if not source_blocks:
        return []

    fts_scores = (
        _fts_scores_with_index(index, _field_terms(field))
        if index is not None
        else _fts_scores(source_blocks, _field_terms(field))
    )
    scored: list[tuple[DocumentIRBlock, float, list[str], list[str]]] = []
    for block in source_blocks:
        if block.section_label in field.excluded_sections:
            continue
        score, match_terms, reasons = _score_block(block, field)
        if block.block_id in fts_scores:
            score += fts_scores[block.block_id]
            reasons.append("fts5_match")
        if score <= 0:
            continue
        scored.append((block, score, match_terms, reasons))
    if not scored and not field.llm.skip_when_no_evidence:
        scored.extend(
            (block, 0.25, [], ["source_section_fallback"])
            for block in _fallback_source_blocks(source_blocks, field)
        )

    scored.sort(key=lambda item: (item[1], item[0].confidence, -item[0].reading_order), reverse=True)
    budget = max(1, min(field.llm.evidence_budget, group_budget or field.llm.evidence_budget))
    max_items = max(1, field.llm.max_evidence_items)
    packs: list[EvidencePack] = []
    seen_hashes: set[str] = set()
    for block, score, match_terms, reasons in scored:
        if len(packs) >= max_items:
            break
        context_blocks = _context_blocks(source_blocks, block)
        context_text = _truncate_context(context_blocks, budget)
        pack_hash = _pack_hash(field.key, context_text)
        if pack_hash in seen_hashes:
            continue
        seen_hashes.add(pack_hash)
        window = _context_window_text(context_blocks, block)
        packs.append(
            EvidencePack(
                field_key=field.key,
                pack_hash=pack_hash,
                rank=len(packs) + 1,
                block_id=block.block_id,
                text=block.text,
                context_text=context_text,
                page=block.page,
                bbox=block.bbox,
                section_label=block.section_label,
                document_kind=block.document_kind,
                ocr_confidence=block.confidence,
                score=round(score, 4),
                match_terms=list(dict.fromkeys(match_terms)),
                score_reason="; ".join(reasons) if reasons else None,
                negated=_has_marker(window, NEGATION_MARKERS, match_terms),
                uncertain=_has_marker(window, UNCERTAIN_MARKERS, match_terms),
                family_context=block.section_label == "家族史" or _has_marker(block.text, FAMILY_MARKERS, match_terms),
                token_estimate=_token_estimate(context_text),
                neighbor_block_ids=[item.block_id for item in context_blocks if item.block_id != block.block_id and item.block_id in block_by_id],
            )
        )
    return packs


def compact_group_context(
    group: FieldGroup,
    fields: list[FieldDefinition],
    blocks: list[DocumentIRBlock],
) -> list[dict]:
    field_ranked = {field.key: build_evidence_packs(None, field, blocks=blocks) for field in fields}
    candidate_block_ids = {pack.block_id for candidates in field_ranked.values() for pack in candidates}
    ranked = sorted(
        blocks,
        key=lambda block: (
            block.block_id in candidate_block_ids,
            _group_block_score(block, fields),
            block.confidence,
        ),
        reverse=True,
    )
    remaining = group.max_context_chars
    compacted: list[dict] = []
    for block in ranked:
        if remaining <= 0:
            break
        text = block.text.strip()
        if not text:
            continue
        if len(text) > remaining:
            text = text[: max(0, remaining - 3)] + "..."
        compacted.append(
            {
                "block_id": block.block_id,
                "page": block.page,
                "reading_order": block.reading_order,
                "section_label": block.section_label,
                "document_kind": block.document_kind,
                "confidence": block.confidence,
                "text": text,
            }
        )
        remaining -= len(text)
    return compacted


def _score_block(block: DocumentIRBlock, field: FieldDefinition) -> tuple[float, list[str], list[str]]:
    score = 0.0
    match_terms: list[str] = []
    reasons: list[str] = []
    if block.section_label in field.source_sections:
        score += 2.0
        reasons.append(f"source_section:{block.section_label}")
    if block.section_label in field.evidence_priority:
        score += 2.0
        reasons.append(f"priority_section:{block.section_label}")
    haystack = block.text
    for term in _field_terms(field):
        if term and term in haystack:
            score += 1.0
            match_terms.append(term)
    if match_terms:
        reasons.append("term_match")
    return score, list(dict.fromkeys(match_terms)), reasons


def _group_block_score(block: DocumentIRBlock, fields: list[FieldDefinition]) -> float:
    score = 0.0
    for field in fields:
        score += _score_block(block, field)[0]
    return score


def _field_terms(field: FieldDefinition) -> list[str]:
    terms = [field.label, *field.synonyms, *field.negation_terms]
    for values in field.code_map.values():
        terms.extend(values)
    return [term for term in dict.fromkeys(terms) if term]


def _fts_scores(blocks: list[DocumentIRBlock], terms: list[str]) -> dict[str, float]:
    """Build-on-demand FTS5 scoring path for callers without an index.

    Construct a temporary in-memory index, run the query, and close the
    connection. Used by call sites that cannot reuse a per-case index
    (legacy ``compact_group_context`` and ad-hoc test helpers).
    """
    query_terms = [term for term in terms if _fts_queryable(term)]
    if not query_terms:
        return {}
    index = build_evidence_index(blocks)
    try:
        return _fts_scores_with_index(index, terms)
    finally:
        index.close()


def _fts_scores_with_index(index: EvidenceIndex, terms: list[str]) -> dict[str, float]:
    """Run FTS5 scoring against the connection owned by ``index``.

    The ``index`` is built once per case; this function is invoked once
    per field with the field's term set. When the index could not
    create an FTS5 connection (very old SQLite builds), returns an
    empty dict so the caller falls back to non-FTS scoring exactly the
    way ``_fts_scores`` did.
    """
    if index.connection is None:
        return {}
    query_terms = [term for term in terms if _fts_queryable(term)]
    if not query_terms:
        return {}
    query = " OR ".join(f'"{term}"' for term in query_terms[:12])
    try:
        rows = index.connection.execute(
            "SELECT block_id, rank FROM block_fts WHERE block_fts MATCH ?",
            (query,),
        ).fetchall()
    except Exception:
        return {}
    scores: dict[str, float] = {}
    for block_id, rank in rows:
        scores[str(block_id)] = max(scores.get(str(block_id), 0.0), 1.0 + abs(float(rank or 0.0)))
    return scores


def _fts_queryable(term: str) -> bool:
    return bool(term and (re.search(r"[A-Za-z0-9]", term) or len(term) >= 2))


def _context_blocks(blocks: list[DocumentIRBlock], center: DocumentIRBlock) -> list[DocumentIRBlock]:
    ordered = sorted(blocks, key=lambda item: (item.page, item.reading_order, item.block_id))
    index = next((idx for idx, item in enumerate(ordered) if item.block_id == center.block_id), -1)
    if index < 0:
        return [center]
    start = max(0, index - 1)
    end = min(len(ordered), index + 2)
    context = [item for item in ordered[start:end] if item.page == center.page]
    if center.table_id:
        row_cells = [
            item
            for item in ordered
            if item.page == center.page
            and item.table_id == center.table_id
            and item.row is not None
            and center.row is not None
            and item.row == center.row
        ]
        context.extend(row_cells)
    by_id = {item.block_id: item for item in context}
    return sorted(by_id.values(), key=lambda item: (item.page, item.reading_order, item.row or 0, item.col or 0, item.block_id))


def _fallback_source_blocks(blocks: list[DocumentIRBlock], field: FieldDefinition) -> list[DocumentIRBlock]:
    if not field.source_sections and not field.evidence_priority:
        return []
    candidates = [
        block
        for block in blocks
        if block.section_label not in field.excluded_sections
        and (block.section_label in field.source_sections or block.section_label in field.evidence_priority)
        and block.text.strip()
    ]
    if not candidates and field.source_sections:
        candidates = [
            block
            for block in blocks
            if block.section_label not in field.excluded_sections and block.text.strip()
        ]
    candidates.sort(
        key=lambda block: (
            _mentions_source_section(block, field),
            block.section_label in field.evidence_priority,
            block.block_type in {"table", "cell", "form_field", "key_value"},
            block.confidence,
            len(block.text),
        ),
        reverse=True,
    )
    return candidates[: max(1, field.llm.max_evidence_items)]


def _mentions_source_section(block: DocumentIRBlock, field: FieldDefinition) -> bool:
    prefix = block.text[:40]
    return any(section and section in prefix for section in [*field.source_sections, *field.evidence_priority])


def _truncate_context(blocks: list[DocumentIRBlock], budget: int) -> str:
    text = "\n".join(item.text.strip() for item in blocks if item.text.strip())
    if len(text) <= budget:
        return text
    return text[: max(0, budget - 3)] + "..."


def _context_window_text(blocks: list[DocumentIRBlock], center: DocumentIRBlock) -> str:
    text = "\n".join(item.text for item in blocks)
    return text or center.text


def _pack_hash(field_key: str, context_text: str) -> str:
    normalized = re.sub(r"\s+", "", context_text)
    return hashlib.sha256(f"{field_key}:{normalized}".encode("utf-8")).hexdigest()[:20]


def _has_marker(text: str, markers: tuple[str, ...], match_terms: list[str]) -> bool:
    if not any(marker in text for marker in markers):
        return False
    if not match_terms:
        return True
    for term in match_terms:
        index = text.find(term)
        if index < 0:
            continue
        window = text[max(0, index - 24) : index + len(term) + 24]
        if any(marker in window for marker in markers):
            return True
    return False


def _token_estimate(text: str) -> int:
    return max(1, math.ceil(len(text) / 2))
