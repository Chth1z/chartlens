from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.core.database import CaseRecord, FieldResultRecord, SessionLocal
from app.core.settings import settings
from app.domain.models import (
    DocumentIR,
    DocumentIRBlock,
    ExtractionCandidate,
    ExtractionSchema,
    FieldDefinition,
    FieldGroup,
    LlmFieldConfig,
    ValidatedFieldResult,
)
from app.main import app
from app.services import ocr, pipeline
from app.services.evidence import build_evidence_packs
from app.services.pipeline import extract_document
from app.services.llm_provider.cache import _llm_cache_key, _read_llm_result_cache, _write_llm_result_cache
from app.services.llm_provider.payloads import _responses_payload
from app.services.llm_provider.types import SemanticExtractionProvider


class CountingProvider(SemanticExtractionProvider):
    name = "counting-provider"
    route = "online_llm"

    def __init__(self) -> None:
        self.calls = 0

    def extract_group(self, *, document_ir, group, fields, blocks):
        self.calls += 1
        return [
            ExtractionCandidate(
                field_key=field.key,
                field_group_key=field.field_group_key,
                normalized_code="unknown",
                status="not_mentioned",
                evidence_type="no_evidence",
                review_required=True,
            )
            for field in fields
        ]

    def collect_evidence(self, *, document_context, fields):
        # CountingProvider only counts extract_group calls; provide a
        # minimal evidence shape so the ABC contract is satisfied.
        return {field.key: [] for field in fields}


def _profile():
    return SimpleNamespace(
        profile_id="openai_structured",
        prompt_cache_key="eyex-test",
        max_output_tokens=4096,
        reasoning_effort="low",
        model="gpt-test",
    )


def test_evidence_packs_rank_context_and_budget():
    field = FieldDefinition(
        key="hypertension_history",
        field_group_key="history_group",
        label="高血压病史",
        export_header="高血压病史",
        allowed_codes=["1", "0", "unknown"],
        source_sections=["既往史"],
        excluded_sections=["家族史"],
        synonyms=["高血压"],
        negation_terms=["否认", "无"],
        evidence_priority=["既往史"],
        llm=LlmFieldConfig(evidence_budget=36, max_evidence_items=2),
    )
    document_ir = DocumentIR(
        document_id="case-evidence",
        profile_id="medical_inpatient_zh",
        source_filename="case.txt",
        blocks=[
            DocumentIRBlock(block_id="b1", page=1, reading_order=1, text="现病史：头痛三天。", section_label="现病史", confidence=0.97),
            DocumentIRBlock(block_id="b2", page=1, reading_order=2, text="既往史：否认高血压、糖尿病。", section_label="既往史", confidence=0.96),
            DocumentIRBlock(block_id="b3", page=1, reading_order=3, text="家族史：父亲有高血压。", section_label="家族史", confidence=0.98),
        ],
    )

    packs = build_evidence_packs(document_ir, field)

    assert [pack.block_id for pack in packs] == ["b2"]
    assert packs[0].pack_hash
    assert packs[0].negated is True
    assert packs[0].family_context is False
    assert packs[0].token_estimate > 0
    assert len(packs[0].context_text) <= 39
    assert "source_section:既往史" in (packs[0].score_reason or "")


def test_skip_when_no_evidence_avoids_provider_call(monkeypatch):
    group = FieldGroup(key="mock_group", label="Mock", semantic_strategy="llm_semantic")
    field = FieldDefinition(
        key="ocular_pressure",
        field_group_key=group.key,
        label="眼压",
        export_header="眼压",
        allowed_codes=["1", "unknown"],
        synonyms=["眼压"],
        llm=LlmFieldConfig(skip_when_no_evidence=True),
    )
    schema = ExtractionSchema(schema_id="mock_schema", version="1.0", label="Mock", field_groups=[group], fields=[field])
    document_ir = DocumentIR(
        document_id="case-skip",
        profile_id="mock_profile",
        source_filename="case.txt",
        blocks=[DocumentIRBlock(block_id="b1", page=1, reading_order=1, text="主诉：头痛。", section_label="主诉", confidence=0.98)],
    )
    semantic_provider = CountingProvider()
    monkeypatch.setattr(pipeline, "load_extraction_schema", lambda: schema)

    results = extract_document(document_ir, provider=semantic_provider)

    assert semantic_provider.calls == 0
    assert results[0].normalized_code == "unknown"
    assert results[0].error_code == "NO_EVIDENCE_CANDIDATES_SKIPPED_LLM"
    assert results[0].provenance["route"] == "skipped_no_evidence"


def test_responses_payload_uses_evidence_packs_without_group_blocks():
    group = FieldGroup(key="history_group", label="病史", max_context_chars=3600)
    field = FieldDefinition(
        key="hypertension_history",
        field_group_key=group.key,
        label="高血压病史",
        export_header="高血压病史",
        allowed_codes=["1", "0", "unknown"],
        synonyms=["高血压"],
        negation_terms=["否认"],
    )
    document_ir = DocumentIR(
        document_id="case-payload",
        profile_id="medical_inpatient_zh",
        source_filename="case.txt",
        blocks=[DocumentIRBlock(block_id="b1", page=1, reading_order=1, text="既往史：否认高血压。", section_label="既往史", confidence=0.98)],
    )

    payload = _responses_payload(
        document_ir=document_ir,
        group=group,
        fields=[field],
        blocks=document_ir.blocks,
        model="gpt-test",
        profile=_profile(),
    )
    user_payload = json.loads(payload["input"][1]["content"])

    assert "evidence_packs" in user_payload
    assert "blocks" not in user_payload
    assert user_payload["evidence_packs"]["hypertension_history"][0]["pack_hash"]


def test_llm_result_cache_round_trips_by_evidence_hash(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_dir", tmp_path)
    group = FieldGroup(key="history_group", label="病史")
    field = FieldDefinition(
        key="hypertension_history",
        field_group_key=group.key,
        label="高血压病史",
        export_header="高血压病史",
        allowed_codes=["1", "0", "unknown"],
        synonyms=["高血压"],
    )
    block = DocumentIRBlock(block_id="b1", page=1, reading_order=1, text="既往史：高血压。", section_label="既往史", confidence=0.98)
    document_ir = DocumentIR(document_id="case-cache", profile_id="medical_inpatient_zh", source_filename="case.txt", blocks=[block])
    cache_key = _llm_cache_key(_profile(), document_ir, group, [field], [block])
    candidate = ExtractionCandidate(
        field_key=field.key,
        field_group_key=field.field_group_key,
        normalized_code="1",
        evidence_span="高血压",
        evidence_block_id="b1",
        evidence_type="explicit_positive",
        confidence=0.91,
        review_required=False,
    )

    _write_llm_result_cache(cache_key, [candidate])
    cached = _read_llm_result_cache(cache_key)

    assert cached is not None
    assert cached[0].field_key == field.key
    assert cached[0].normalized_code == "1"


def test_evidence_falls_back_to_source_section_when_terms_are_sparse():
    field = FieldDefinition(
        key="discharge_status",
        field_group_key="discharge_group",
        label="出院结局",
        export_header="出院结局",
        allowed_codes=["1", "0", "unknown"],
        source_sections=["出院情况"],
        synonyms=["死亡"],
        llm=LlmFieldConfig(evidence_budget=120, max_evidence_items=1),
    )
    document_ir = DocumentIR(
        document_id="case-section-fallback",
        profile_id="medical_inpatient_zh",
        source_filename="case.txt",
        blocks=[
            DocumentIRBlock(block_id="b1", page=1, reading_order=1, text="主诉：头痛。", section_label="主诉", confidence=0.98),
            DocumentIRBlock(block_id="b2", page=2, reading_order=2, text="出院情况：患者神志清，生命体征平稳。", section_label="未知", confidence=0.96),
        ],
    )

    packs = build_evidence_packs(document_ir, field)

    assert [pack.block_id for pack in packs] == ["b2"]
    assert "source_section_fallback" in (packs[0].score_reason or "")


def test_table_cell_evidence_context_includes_same_row_cells():
    field = FieldDefinition(
        key="gender",
        field_group_key="demographics_group",
        label="性别",
        export_header="性别",
        allowed_codes=["1", "2", "unknown"],
        source_sections=["病案首页"],
        synonyms=["性别"],
        llm=LlmFieldConfig(evidence_budget=200, max_evidence_items=1),
    )
    document_ir = DocumentIR(
        document_id="case-table",
        profile_id="medical_inpatient_zh",
        source_filename="case.txt",
        blocks=[
            DocumentIRBlock(
                block_id="b1",
                page=1,
                reading_order=1,
                text="性别",
                section_label="病案首页",
                confidence=0.98,
                block_type="cell",
                table_id="t1",
                row=1,
                col=1,
            ),
            DocumentIRBlock(
                block_id="b2",
                page=1,
                reading_order=2,
                text="女",
                section_label="病案首页",
                confidence=0.98,
                block_type="cell",
                table_id="t1",
                row=1,
                col=2,
            ),
        ],
    )

    packs = build_evidence_packs(document_ir, field)

    assert packs[0].block_id == "b1"
    assert "性别" in packs[0].context_text
    assert "女" in packs[0].context_text
    assert "b2" in packs[0].neighbor_block_ids


def test_evaluation_profile_loader_and_api_are_config_driven(monkeypatch, tmp_path):
    config_dir = tmp_path / "config"
    profile_dir = config_dir / "evaluation_profiles"
    profile_dir.mkdir(parents=True)
    (profile_dir / "mock_general.yaml").write_text(
        """
profile_id: mock_general
label: Mock 通用评测
schema_id: mock_schema
field_tags:
  ocular_pressure: [ophthalmology, numeric]
thresholds:
  auto_accept_precision: 0.95
token_budget:
  max_input_tokens_per_case: 1200
gold_cases:
  - case_id: CASE-EVAL-PROFILE
    tags: [ophthalmology]
    gold:
      ocular_pressure: "1"
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "config_dir", config_dir)

    db = SessionLocal()
    case_id = "CASE-EVAL-PROFILE"
    try:
        db.query(FieldResultRecord).filter(FieldResultRecord.case_id == case_id).delete()
        db.query(CaseRecord).filter(CaseRecord.case_id == case_id).delete()
        db.commit()
        db.add(
            CaseRecord(
                case_id=case_id,
                filename="case.txt",
                file_hash="hash",
                file_path="case.txt",
                status="completed",
                diagnostics_json=json.dumps({"llm_usage": [{"usage": {"input_tokens": 100, "output_tokens": 20}}]}),
            )
        )
        db.add(
            FieldResultRecord(
                case_id=case_id,
                field_key="ocular_pressure",
                payload_json=ValidatedFieldResult(
                    field_key="ocular_pressure",
                    field_group_key="mock_group",
                    normalized_code="1",
                    status="confirmed",
                    confidence=0.95,
                    evidence_span="眼压升高",
                    evidence_block_id="b1",
                    auto_accepted=True,
                    review_required=False,
                ).model_dump_json(),
            )
        )
        db.commit()

        response = TestClient(app).post("/api/evals/profiles/mock_general/run")
    finally:
        db.query(FieldResultRecord).filter(FieldResultRecord.case_id == case_id).delete()
        db.query(CaseRecord).filter(CaseRecord.case_id == case_id).delete()
        db.commit()
        db.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["profile"]["profile_id"] == "mock_general"
    assert payload["summary"]["tokens_per_case"] == 100
    assert payload["summary"]["tokens_per_accepted_field"] == 100
    assert payload["summary"]["field_tags"]["ophthalmology"]["accuracy"] == 1.0


def test_ocr_cache_is_content_based_across_paths(monkeypatch, tmp_path):
    first = tmp_path / "a.png"
    second = tmp_path / "nested" / "b.png"
    second.parent.mkdir()
    first.write_bytes(b"same-image")
    second.write_bytes(b"same-image")
    calls = {"count": 0}

    def fake_intelligent_extract(file_path, aliases):
        calls["count"] += 1
        return [
            DocumentIRBlock(block_id="b1", page=1, reading_order=1, text="姓名：张三", confidence=0.95),
        ], {"ocr_engine": "fixture", "ocr_intelligent_status": "completed"}

    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    monkeypatch.setattr(ocr, "extract_with_intelligent_ocr", fake_intelligent_extract)

    ocr.build_document_ir(first, first.read_bytes(), document_id="case-a")
    second_ir = ocr.build_document_ir(second, second.read_bytes(), document_id="case-b")

    assert calls["count"] == 1
    assert second_ir.metadata["ocr_cache_status"] == "hit"
    assert second_ir.metadata["ocr_page_quality"][0]["cache_status"] == "hit"


def test_pdf_ocr_metadata_preserves_candidate_debug_metrics(monkeypatch, tmp_path):
    pdf = tmp_path / "case.pdf"
    pdf.write_bytes(b"%PDF fixture")

    def fake_intelligent_extract(file_path, aliases, **kwargs):
        return [
            DocumentIRBlock(block_id="b1", page=1, reading_order=1, text="现病史：腹痛", confidence=0.95),
        ], {
            "ocr_engine": "paddleocr_hybrid",
            "ocr_intelligent_status": "completed",
            "render_dpi_candidates": [300, 400],
            "render_dpi": 300,
            "tile_max_side_len": 1536,
            "tile_overlap": 192,
            "image_preprocess_modes": ["none"],
            "ocr_candidate_metrics": [
                {"render_dpi": 300, "char_count": 20, "avg_confidence": 0.95, "selected": True},
                {"render_dpi": 400, "char_count": 16, "avg_confidence": 0.91, "selected": False},
            ],
        }

    monkeypatch.setattr(ocr, "_extract_pdf_text_pages", lambda file_path: [(1, "")])
    monkeypatch.setattr(ocr, "extract_with_intelligent_ocr", fake_intelligent_extract)
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")

    document_ir = ocr.build_document_ir(pdf, pdf.read_bytes(), document_id="case-pdf-ocr")

    assert document_ir.metadata["ocr_candidate_metrics"][0]["render_dpi"] == 300
    assert document_ir.metadata["render_dpi_candidates"] == [300, 400]
    assert document_ir.metadata["tile_overlap"] == 192


def test_native_pdf_metadata_reports_page_quality(monkeypatch, tmp_path):
    pdf = tmp_path / "case.pdf"
    pdf.write_bytes(b"%PDF fixture")
    monkeypatch.setattr(
        ocr,
        "_extract_pdf_text_pages",
        lambda file_path: [(1, "基本信息：患者男性，年龄六十六岁，入院记录完整。"), (2, "既往史：否认高血压、糖尿病、冠心病等慢性病。")],
    )

    document_ir = ocr.build_document_ir(pdf, pdf.read_bytes(), document_id="case-pdf")

    assert document_ir.metadata["ocr_page_quality"] == [
        {"page": 1, "kind": "native_pdf_text", "char_count": 24, "avg_confidence": 0.98, "quality_band": "good", "cache_status": "not_applicable", "engine": "pdf_text"},
        {"page": 2, "kind": "native_pdf_text", "char_count": 22, "avg_confidence": 0.98, "quality_band": "good", "cache_status": "not_applicable", "engine": "pdf_text"},
    ]
