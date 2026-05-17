from app.core.config_loader import load_extraction_schema
from app.domain.models import DocumentIR, DocumentIRBlock, EvidenceCandidate
from app.services.document_context import build_document_context, document_context_payload
from app.services.evidence_first import (
    adjudicate_field_decisions,
    collect_local_evidence,
    decisions_to_extraction_candidates,
)


def _document_ir(blocks: list[DocumentIRBlock], *, metadata: dict | None = None) -> DocumentIR:
    return DocumentIR(
        document_id="ctx-case",
        profile_id="medical_inpatient_zh",
        source_filename="case.pdf",
        blocks=blocks,
        metadata=metadata or {},
    )


def test_document_context_keeps_full_page_layout_and_tables():
    document_ir = _document_ir(
        [
            DocumentIRBlock(
                block_id="b-title",
                page=1,
                reading_order=1,
                text="某某医院住院病案首页",
                bbox=[0, 0, 800, 80],
                confidence=0.98,
                block_type="title",
                source_engine="paddleocr_hybrid",
            ),
            DocumentIRBlock(
                block_id="b-cell",
                page=1,
                reading_order=2,
                text="性别：男",
                bbox=[320, 120, 380, 150],
                confidence=0.97,
                block_type="cell",
                table_id="t1",
                row=1,
                col=4,
                source_engine="pp_structure_v3",
            ),
            DocumentIRBlock(
                block_id="b-history",
                page=2,
                reading_order=1,
                text="既往史：否认糖尿病。",
                bbox=[40, 300, 720, 340],
                confidence=0.96,
                block_type="paragraph",
                section_label="既往史",
                source_engine="pp_ocr_v5",
            ),
        ],
        metadata={
            "page_images": [
                {"page": 1, "path": "var/storage/page_images/ctx-case/page-0001.png", "width": 1200, "height": 1600}
            ]
        },
    )

    context = build_document_context(document_ir)
    payload = document_context_payload(context, include_images=False)

    assert [page.page for page in context.pages] == [1, 2]
    assert context.pages[0].image is not None
    assert context.pages[0].tables[0]["table_id"] == "t1"
    assert context.pages[0].tables[0]["cells"][0]["block_id"] == "b-cell"
    assert payload["pages"][0]["blocks"][1]["text"] == "性别：男"
    assert payload["pages"][1]["blocks"][0]["section_label"] == "既往史"


def test_local_evidence_collection_does_not_turn_family_children_into_gender():
    schema = load_extraction_schema()
    gender = schema.field_by_key("gender")
    document_ir = _document_ir(
        [
            DocumentIRBlock(
                block_id="b-family",
                page=1,
                reading_order=1,
                text="夫妻关系和睦，有一子两女，皆体健。",
                confidence=0.99,
                section_label="家族史",
            )
        ]
    )

    evidence = collect_local_evidence(build_document_context(document_ir), [gender])
    decisions = adjudicate_field_decisions([gender], evidence)

    assert evidence[gender.key] == []
    assert decisions[gender.key].decision_status == "MISSING"
    assert decisions[gender.key].needs_human_review is True


def test_local_evidence_collection_maps_explicit_negative_history_to_zero():
    schema = load_extraction_schema()
    diabetes = schema.field_by_key("diabetes_history")
    document_ir = _document_ir(
        [
            DocumentIRBlock(
                block_id="b-history",
                page=1,
                reading_order=1,
                text="既往史：否认高血压病、糖尿病等病史。",
                confidence=0.98,
                section_label="既往史",
            )
        ]
    )

    evidence = collect_local_evidence(build_document_context(document_ir), [diabetes])
    decisions = adjudicate_field_decisions([diabetes], evidence)
    candidates = decisions_to_extraction_candidates([diabetes], decisions)

    assert decisions[diabetes.key].decision_status == "PASS"
    assert candidates[0].normalized_code == "0"
    assert candidates[0].evidence_type == "explicit_negative"
    assert candidates[0].evidence_span == "否认高血压病、糖尿病等病史"


def test_local_evidence_rejects_family_pregnancy_history_when_section_missing():
    schema = load_extraction_schema()
    diabetes = schema.field_by_key("diabetes_history")
    hypertension = schema.field_by_key("hypertension_history")
    document_ir = _document_ir(
        [
            DocumentIRBlock(
                block_id="b-family-inline",
                page=1,
                reading_order=1,
                text="家族史：父母体健。其母孕期体健，否认妊娠期高血压及糖尿病史。",
                confidence=0.98,
                section_label="未知",
            )
        ]
    )

    evidence = collect_local_evidence(build_document_context(document_ir), [diabetes, hypertension])
    decisions = adjudicate_field_decisions([diabetes, hypertension], evidence)

    assert all(candidate.forbidden_inference_flags == ["family_context"] for candidate in evidence[diabetes.key])
    assert decisions[diabetes.key].decision_status == "MISSING"
    assert decisions[hypertension.key].decision_status == "MISSING"


def test_field_adjudication_surfaces_conflicts_instead_of_guessing():
    schema = load_extraction_schema()
    gender = schema.field_by_key("gender")
    evidence = {
        gender.key: [
            EvidenceCandidate(
                field_key=gender.key,
                candidate_value="男",
                normalized_code="1",
                block_id="b1",
                block_ids=["b1"],
                text="性别：男",
                evidence_text="性别：男",
                page=1,
                confidence=0.96,
                score=0.96,
                source_type="ocr_text",
            ),
            EvidenceCandidate(
                field_key=gender.key,
                candidate_value="女",
                normalized_code="2",
                block_id="b2",
                block_ids=["b2"],
                text="性别：女",
                evidence_text="性别：女",
                page=3,
                confidence=0.95,
                score=0.95,
                source_type="ocr_text",
            ),
        ]
    }

    decisions = adjudicate_field_decisions([gender], evidence)

    assert decisions[gender.key].decision_status == "CONFLICT"
    assert decisions[gender.key].normalized_code == "unknown"
    assert len(decisions[gender.key].conflict_candidates) == 2
    assert decisions[gender.key].needs_human_review is True
