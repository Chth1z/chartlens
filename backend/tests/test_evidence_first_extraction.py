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


def test_positive_history_span_does_not_inherit_neighbor_clause_negation():
    """E1-005 regression: a positive 'X病史N年' clause must not be silently
    rejected when the next clause negates a different field.

    Before the fix, the right-side 24-char window of `_positive_span` could
    swallow text past the sentence terminator, so '高血压病史10年。否认糖尿
    病史。' would see '否认' inside the candidate window for hypertension and
    discard the positive evidence. This test pins the corrected behavior.
    """
    schema = load_extraction_schema()
    hypertension = schema.field_by_key("hypertension_history")
    document_ir = _document_ir(
        [
            DocumentIRBlock(
                block_id="b-history",
                page=1,
                reading_order=1,
                text="既往史：高血压病史10年，规律服药控制。否认糖尿病史。",
                confidence=0.97,
                section_label="既往史",
            )
        ]
    )

    evidence = collect_local_evidence(build_document_context(document_ir), [hypertension])
    decisions = adjudicate_field_decisions([hypertension], evidence)
    candidates = decisions_to_extraction_candidates([hypertension], decisions)

    assert decisions[hypertension.key].decision_status == "PASS"
    assert candidates[0].normalized_code == "1"
    assert candidates[0].evidence_type == "explicit_positive"
    assert "高血压病史" in (candidates[0].evidence_span or "")
    # The neighboring '否认糖尿病史' clause must not appear inside the
    # hypertension evidence span.
    assert "否认" not in (candidates[0].evidence_span or "")


def test_smoking_history_positive_span_is_clause_bounded():
    """E1-005 regression: 吸烟史 with a duration clause should not be
    suppressed by a following 否认饮酒史 clause."""
    schema = load_extraction_schema()
    smoking = schema.field_by_key("smoking_history")
    document_ir = _document_ir(
        [
            DocumentIRBlock(
                block_id="b-personal",
                page=1,
                reading_order=1,
                text="个人史：吸烟史20年，每日10支。否认饮酒史。",
                confidence=0.97,
                section_label="个人史",
            )
        ]
    )

    evidence = collect_local_evidence(build_document_context(document_ir), [smoking])
    decisions = adjudicate_field_decisions([smoking], evidence)
    candidates = decisions_to_extraction_candidates([smoking], decisions)

    assert decisions[smoking.key].decision_status == "PASS"
    assert candidates[0].normalized_code == "1"
    assert candidates[0].evidence_type == "explicit_positive"
    assert "吸烟史" in (candidates[0].evidence_span or "")
    assert "否认" not in (candidates[0].evidence_span or "")


def test_non_standard_hypertension_phrasing_is_recognized():
    """E1-005 synonym widening: '血压偏高' was added to hypertension synonyms
    so the rule path now lifts it to a positive code instead of falling back
    to MISSING. Previous behavior (MISSING) was pinned; this test inverts
    the assertion alongside the synonym-widening commit.
    """
    schema = load_extraction_schema()
    hypertension = schema.field_by_key("hypertension_history")
    document_ir = _document_ir(
        [
            DocumentIRBlock(
                block_id="b-history",
                page=1,
                reading_order=1,
                text="既往史：血压偏高8年，未规律服药。",
                confidence=0.97,
                section_label="既往史",
            )
        ]
    )

    evidence = collect_local_evidence(build_document_context(document_ir), [hypertension])
    decisions = adjudicate_field_decisions([hypertension], evidence)
    candidates = decisions_to_extraction_candidates([hypertension], decisions)

    assert decisions[hypertension.key].decision_status == "PASS"
    assert candidates[0].normalized_code == "1"
    assert candidates[0].evidence_type == "explicit_positive"
    assert "血压偏高" in (candidates[0].evidence_span or "")


def test_non_standard_drinking_phrasing_is_recognized():
    """E1-005 synonym widening: '嗜酒' was added to drinking_history synonyms
    so the rule path now lifts it to a positive code. Previous behavior
    (MISSING) was pinned; this test inverts the assertion alongside the
    synonym-widening commit.
    """
    schema = load_extraction_schema()
    drinking = schema.field_by_key("drinking_history")
    document_ir = _document_ir(
        [
            DocumentIRBlock(
                block_id="b-personal",
                page=1,
                reading_order=1,
                text="个人史：嗜酒30年，每日饮白酒约半斤。否认吸烟史。",
                confidence=0.97,
                section_label="个人史",
            )
        ]
    )

    evidence = collect_local_evidence(build_document_context(document_ir), [drinking])
    decisions = adjudicate_field_decisions([drinking], evidence)
    candidates = decisions_to_extraction_candidates([drinking], decisions)

    assert decisions[drinking.key].decision_status == "PASS"
    assert candidates[0].normalized_code == "1"
    assert candidates[0].evidence_type == "explicit_positive"
    assert "嗜酒" in (candidates[0].evidence_span or "")


def test_rule_shortcut_high_confidence_skips_llm_collect_evidence():
    """E1-005 rule_pre_accepted: when a phase-1 field belongs to a group
    whose `semantic_strategy == "rule_shortcut"` AND `rule_shortcut_extract`
    returns a candidate at confidence >= 0.95, the candidate must bypass
    the LLM evidence-first pipeline entirely.

    Concretely: for `基本信息：患者，男，72岁。` the demographics rule path
    (`_extract_age` / `_extract_gender`) returns confidence 0.96. The LLM
    `collect_evidence` must never see `age` or `gender` in its `fields`
    argument, and the returned `age` ValidatedFieldResult must carry
    `acceptance_reason='rule_pre_accepted'` plus a provenance shape that
    surfaces the skipped-LLM decision in diagnostics.
    """
    from app.domain.models import EvidenceCandidate as _EvidenceCandidate
    from app.services.llm_provider.types import (
        SemanticExtractionProvider,
        local_collect_evidence_fallback,
        local_evidence_fallback_usage,
    )
    from app.services.pipeline import extract_document

    document_ir = _document_ir(
        [
            DocumentIRBlock(
                block_id="b-demo",
                page=1,
                reading_order=1,
                text="基本信息：患者，男，72岁。",
                bbox=[0, 0, 800, 60],
                confidence=0.99,
                block_type="paragraph",
                section_label="基本信息",
                source_engine="pp_ocr_v5",
            ),
        ],
        metadata={"deidentification": {"online_llm_allowed": True}},
    )

    class _AssertingFakeProvider(SemanticExtractionProvider):
        """Fake provider that asserts `age` is never in `collect_evidence` fields.

        Designed for the rule_pre_accepted pinning test: the demographics
        rule path returns `age` at confidence 0.96, so the pipeline must
        bypass the LLM and never include `age` in the `fields` list passed
        to `collect_evidence`. If it does, this fake raises immediately
        instead of silently returning evidence.
        """

        name = "asserting-fake-provider"
        route = "test-fake"

        def __init__(self) -> None:
            self.collect_evidence_calls: list[list[str]] = []

        def extract_group(self, *, document_ir, group, fields, blocks):  # pragma: no cover - unused path
            del document_ir, group, blocks
            return []

        def collect_evidence(self, *, document_context, fields):
            field_keys = [field.key for field in fields]
            self.collect_evidence_calls.append(field_keys)
            if "age" in field_keys:
                raise RuntimeError(
                    "collect_evidence should not be called for rule-pre-accepted age"
                )
            self.last_usage = local_evidence_fallback_usage()
            return local_collect_evidence_fallback(document_context, fields)

    fake_provider = _AssertingFakeProvider()
    results = extract_document(document_ir, provider=fake_provider)

    age_result = next((r for r in results if r.field_key == "age"), None)
    assert age_result is not None, "age result missing from extract_document output"
    assert age_result.normalized_code == "72"
    assert age_result.acceptance_reason == "rule_pre_accepted"
    assert age_result.provenance.get("source") == "rule_shortcut"
    assert age_result.provenance.get("skipped_llm") is True

    # Provider may have been called for other LLM-tier fields (history etc.)
    # but the `age` key must never appear.
    for fields_seen in fake_provider.collect_evidence_calls:
        assert "age" not in fields_seen, (
            f"age leaked into LLM collect_evidence fields list: {fields_seen}"
        )

    # Sanity: at least one call happened (the LLM path covers history /
    # discharge / aneurysm / surgery / score groups). If it never fired,
    # the test would silently pass even with a regression that disables
    # LLM extraction wholesale.
    assert fake_provider.collect_evidence_calls, (
        "fake provider was never called; the test cannot prove age was skipped"
    )

    # `EvidenceCandidate` import is exercised so a future refactor that
    # renames the symbol still keeps this regression test compilable.
    assert _EvidenceCandidate.__name__ == "EvidenceCandidate"
