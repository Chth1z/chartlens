"""Contract tests for the per-case ``EvidenceIndex`` reuse path (M1-002).

The indexed and legacy code paths must produce byte-identical
``EvidencePack`` lists. ``build_evidence_packs`` accepts an optional
``EvidenceIndex`` so the SQLite FTS5 connection is built once per case
and reused across every field; without the index every call rebuilt the
in-memory FTS table. Behavior must be identical so the rule baseline
stays byte-equivalent.
"""
from __future__ import annotations

from app.core.config_loader import load_extraction_schema
from app.domain.models import DocumentIR, DocumentIRBlock
from app.services.evidence import (
    build_evidence_index,
    build_evidence_packs,
    evidence_for_field,
    evidence_index,
)


def _document_ir(blocks: list[DocumentIRBlock]) -> DocumentIR:
    return DocumentIR(
        document_id="idx-case",
        profile_id="medical_inpatient_zh",
        source_filename="case.txt",
        blocks=blocks,
    )


def _fixture_blocks() -> list[DocumentIRBlock]:
    return [
        DocumentIRBlock(
            block_id="b1",
            page=1,
            reading_order=1,
            text="主诉：发作性头痛三天。",
            section_label="主诉",
            confidence=0.96,
        ),
        DocumentIRBlock(
            block_id="b2",
            page=1,
            reading_order=2,
            text="现病史：患者三天前突发头痛，否认高血压、糖尿病。",
            section_label="现病史",
            confidence=0.97,
        ),
        DocumentIRBlock(
            block_id="b3",
            page=1,
            reading_order=3,
            text="既往史：否认高血压、糖尿病、冠心病。",
            section_label="既往史",
            confidence=0.98,
        ),
        DocumentIRBlock(
            block_id="b4",
            page=1,
            reading_order=4,
            text="个人史：否认吸烟、饮酒史。",
            section_label="个人史",
            confidence=0.97,
        ),
        DocumentIRBlock(
            block_id="b5",
            page=1,
            reading_order=5,
            text="家族史：父亲有高血压。",
            section_label="家族史",
            confidence=0.95,
        ),
        DocumentIRBlock(
            block_id="b6",
            page=1,
            reading_order=6,
            text="基本信息：患者，男，58岁。",
            section_label="基本信息",
            confidence=0.99,
        ),
    ]


def _serialize_pack(pack):
    """Pull only the fields that affect downstream contract behavior.

    Comparing the full ``EvidencePack`` model_dump catches everything,
    but listing the attributes explicitly makes the intent obvious if
    the dataclass shape ever changes.
    """
    return (
        pack.field_key,
        pack.pack_hash,
        pack.rank,
        pack.block_id,
        pack.text,
        pack.context_text,
        pack.score,
        tuple(pack.match_terms),
        pack.score_reason,
        pack.negated,
        pack.uncertain,
        pack.family_context,
        pack.token_estimate,
        tuple(pack.neighbor_block_ids),
    )


def test_evidence_index_returns_identical_packs_to_legacy_path():
    schema = load_extraction_schema()
    blocks = _fixture_blocks()
    document_ir = _document_ir(blocks)

    # Pick a handful of real schema fields so the comparison covers the
    # FTS5 query, term matching, dedupe, and context-window math.
    field_keys = [
        "gender",
        "age",
        "hypertension_history",
        "diabetes_history",
        "smoking_history",
        "drinking_history",
    ]

    index = build_evidence_index(blocks)
    try:
        for key in field_keys:
            field = schema.field_by_key(key)
            legacy_packs = build_evidence_packs(document_ir, field, blocks=blocks)
            indexed_packs = build_evidence_packs(
                document_ir, field, blocks=blocks, index=index
            )
            assert [
                _serialize_pack(pack) for pack in legacy_packs
            ] == [
                _serialize_pack(pack) for pack in indexed_packs
            ], f"pack drift for {key}"

            # evidence_for_field flows through build_evidence_packs and
            # converts each pack into an EvidenceCandidate. Same scores,
            # same block_ids, same match_terms.
            legacy_candidates = evidence_for_field(document_ir, field, blocks=blocks)
            indexed_candidates = evidence_for_field(
                document_ir, field, blocks=blocks, index=index
            )
            assert [
                (c.block_id, c.score, c.pack_hash, tuple(c.match_terms), c.score_reason)
                for c in legacy_candidates
            ] == [
                (c.block_id, c.score, c.pack_hash, tuple(c.match_terms), c.score_reason)
                for c in indexed_candidates
            ], f"candidate drift for {key}"
    finally:
        index.close()


def test_evidence_index_close_is_idempotent():
    blocks = _fixture_blocks()
    index = build_evidence_index(blocks)
    index.close()
    # Second close must not raise (e.g., when a try/finally double-closes
    # because the caller also held a `with evidence_index(...)` scope).
    index.close()
    assert index.connection is None


def test_evidence_index_signature_pins_block_set():
    blocks = _fixture_blocks()
    index_a = build_evidence_index(blocks)
    try:
        signature_a = index_a.block_ids_signature
    finally:
        index_a.close()

    # Reordering the input flips the signature so a future stale-index
    # detection can compare signatures cheaply without rehashing the
    # full block payload.
    reversed_blocks = list(reversed(blocks))
    index_b = build_evidence_index(reversed_blocks)
    try:
        signature_b = index_b.block_ids_signature
    finally:
        index_b.close()

    assert signature_a != signature_b


def test_evidence_index_context_manager_closes_connection():
    blocks = _fixture_blocks()
    with evidence_index(blocks) as index:
        assert index.connection is not None
        # Smoke: the indexed query path runs successfully.
        schema = load_extraction_schema()
        gender = schema.field_by_key("gender")
        packs = build_evidence_packs(
            _document_ir(blocks), gender, blocks=blocks, index=index
        )
        assert isinstance(packs, list)
    # On exit the context manager calls close(); the connection field is
    # cleared and a follow-up close() stays a no-op.
    assert index.connection is None
    index.close()
