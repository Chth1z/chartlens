from app.core.config_loader import load_document_profile, load_extraction_schema
from app.domain.models import DocumentIR, DocumentIRBlock
from app.services.deidentify import deidentify_document_ir
from app.services.document_context import build_document_context, document_context_payload
from app.services.evidence_first import adjudicate_field_decisions, collect_local_evidence
from app.services.layout_normalizer import normalize_document_layout


def _block(
    block_id: str,
    text: str,
    *,
    page: int = 1,
    order: int = 1,
    bbox: list[float] | None = None,
) -> DocumentIRBlock:
    return DocumentIRBlock(
        block_id=block_id,
        page=page,
        reading_order=order,
        text=text,
        bbox=bbox or [],
        confidence=0.98,
        section_label="未知",
    )


def _document(blocks: list[DocumentIRBlock]) -> DocumentIR:
    return DocumentIR(
        document_id="case-layout",
        profile_id="medical_inpatient_zh",
        source_filename="case.jpg",
        blocks=blocks,
    )


def test_layout_normalizer_removes_screen_chrome_and_rebuilds_reading_order():
    profile = load_document_profile()
    document_ir = _document(
        [
            _block("chrome", "03-05入院记录（儿）（经治审签）  保存(S) 签名(F6) 打印(P)", order=1, bbox=[0, 0, 900, 24]),
            _block("body", "服用盐酸氨酚拉明片12小时，头晕9小时。", order=2, bbox=[190, 180, 780, 205]),
            _block("title", "主  诉：", order=3, bbox=[80, 180, 180, 205]),
        ]
    )

    normalized = normalize_document_layout(document_ir, profile)

    assert [block.text for block in normalized.blocks] == [
        "主  诉： 服用盐酸氨酚拉明片12小时，头晕9小时。"
    ]
    assert normalized.blocks[0].reading_order == 1
    assert normalized.blocks[0].section_label == "主诉"
    assert normalized.metadata["layout_normalization"]["removed_screen_chrome_blocks"] == 1


def test_layout_normalizer_marks_patient_header_without_overriding_body_section():
    profile = load_document_profile()
    document_ir = _document(
        [
            _block("progress-title", "病 程 记 录", order=1, bbox=[300, 80, 600, 120]),
            _block("header-1", "科室：儿科病房  姓名：李某  性别：男  年龄：16", order=2, bbox=[80, 130, 900, 155]),
            _block("body", "今日查房，患儿一般情况可。", order=3, bbox=[100, 190, 850, 225]),
        ]
    )

    normalized = normalize_document_layout(document_ir, profile)
    by_id = {block.block_id: block for block in normalized.blocks}

    assert by_id["header-1"].section_label == "基本信息"
    assert "layout_patient_header" in by_id["header-1"].quality_flags
    assert by_id["body"].section_label == "病程记录"
    assert by_id["body"].document_kind == "progress_note"


def test_layout_normalizer_assigns_profile_driven_document_regions():
    profile = load_document_profile()
    document_ir = _document(
        [
            _block("progress-title", "病 程 记 录", order=1, bbox=[300, 80, 600, 120]),
            _block("header-1", "科室：儿科病房  姓名：李某  性别：男  年龄：16", order=2, bbox=[80, 130, 900, 155]),
            _block("body", "今日查房，患儿一般情况可。", order=3, bbox=[100, 190, 850, 225]),
            _block("signature", "记录者（术者）：张医生", order=4, bbox=[600, 760, 820, 790]),
        ]
    )

    normalized = normalize_document_layout(document_ir, profile)
    by_id = {block.block_id: block for block in normalized.blocks}

    assert by_id["progress-title"].document_region == "section_heading"
    assert by_id["header-1"].document_region == "patient_header"
    assert by_id["body"].document_region == "clinical_body"
    assert by_id["signature"].document_region == "signature"

    context = build_document_context(normalized)
    payload = document_context_payload(context, include_images=False)
    block_payloads = {block["block_id"]: block for block in payload["pages"][0]["blocks"]}
    assert block_payloads["header-1"]["document_region"] == "patient_header"
    assert block_payloads["signature"]["document_region"] == "signature"

    gender_field = next(field for field in load_extraction_schema().fields if field.key == "gender")
    evidence = collect_local_evidence(context, [gender_field])
    assert evidence["gender"][0].document_region == "patient_header"


def test_layout_normalizer_derives_key_value_blocks_from_patient_header():
    profile = load_document_profile()
    document_ir = _document(
        [
            _block(
                "header-1",
                "科室：儿科病房  姓名：李某  性别：男  年龄：16  床号：56  病案号：1266146",
                order=1,
                bbox=[80, 130, 980, 155],
            ),
            _block("body", "今日查房，患儿一般情况可。", order=2, bbox=[100, 190, 850, 225]),
        ]
    )

    normalized = normalize_document_layout(document_ir, profile)
    derived = [block for block in normalized.blocks if "layout_key_value_pair" in block.quality_flags]
    by_label = {block.key_label: block for block in derived}

    assert by_label["性别"].text == "性别：男"
    assert by_label["性别"].value_text == "男"
    assert by_label["性别"].parent_block_id == "header-1"
    assert by_label["性别"].document_region == "patient_header"
    assert by_label["性别"].bbox
    assert by_label["性别"].bbox[0] >= 80
    assert by_label["性别"].bbox[2] <= 980
    assert "layout_estimated_bbox" in by_label["性别"].quality_flags
    assert by_label["性别"].reading_order == 4
    assert by_label["年龄"].text == "年龄：16"
    assert by_label["病案号"].text == "病案号：1266146"
    assert normalized.metadata["layout_normalization"]["derived_key_value_blocks"] >= 5

    context = build_document_context(normalized)
    payload = document_context_payload(context, include_images=False)
    payload_by_id = {block["block_id"]: block for block in payload["pages"][0]["blocks"]}
    assert payload_by_id[by_label["性别"].block_id]["key_label"] == "性别"
    assert payload_by_id[by_label["性别"].block_id]["value_text"] == "男"
    assert payload_by_id[by_label["性别"].block_id]["parent_block_id"] == "header-1"

    gender_field = next(field for field in load_extraction_schema().fields if field.key == "gender")
    evidence = collect_local_evidence(context, [gender_field])
    assert evidence["gender"][0].source_type == "layout_key_value"
    assert evidence["gender"][0].evidence_text == "性别：男"
    assert evidence["gender"][0].block_id == by_label["性别"].block_id


def test_layout_normalizer_derives_key_values_from_split_patient_header_line():
    profile = load_document_profile()
    document_ir = _document(
        [
            _block("dept-label", "科室：", order=1, bbox=[80, 130, 130, 155]),
            _block("dept-value", "儿科病房", order=2, bbox=[290, 130, 380, 155]),
            _block("name-label", "姓名：", order=3, bbox=[400, 130, 450, 155]),
            _block("name-value", "李某", order=4, bbox=[610, 130, 670, 155]),
            _block("gender-label", "性别：", order=5, bbox=[760, 130, 810, 155]),
            _block("gender-value", "男", order=6, bbox=[970, 130, 990, 155]),
            _block("age-label", "年龄：", order=7, bbox=[1060, 130, 1110, 155]),
            _block("age-value", "16", order=8, bbox=[1270, 130, 1300, 155]),
            _block("case-label", "病案号：", order=9, bbox=[1380, 130, 1460, 155]),
            _block("case-value", "1266146", order=10, bbox=[1620, 130, 1750, 155]),
            _block("body", "今日查房，患儿一般情况可。", order=11, bbox=[100, 190, 850, 225]),
        ]
    )

    normalized = normalize_document_layout(document_ir, profile)
    by_id = {block.block_id: block for block in normalized.blocks}
    derived = [block for block in normalized.blocks if "layout_key_value_pair" in block.quality_flags]
    by_label = {block.key_label: block for block in derived}

    assert by_id["gender-label"].document_region == "patient_header"
    assert "layout_patient_header" in by_id["gender-label"].quality_flags
    assert by_label["性别"].text == "性别：男"
    assert by_label["性别"].value_text == "男"
    assert by_label["性别"].bbox == [760.0, 130.0, 990.0, 155.0]
    assert by_label["性别"].derived_from_block_ids == ["gender-label", "gender-value"]
    assert "layout_neighbor_key_value_pair" in by_label["性别"].quality_flags
    assert by_label["年龄"].text == "年龄：16"
    assert by_label["病案号"].text == "病案号：1266146"
    assert normalized.metadata["layout_normalization"]["derived_neighbor_key_value_blocks"] >= 3

    context = build_document_context(normalized)
    gender_field = next(field for field in load_extraction_schema().fields if field.key == "gender")
    evidence = collect_local_evidence(context, [gender_field])
    assert evidence["gender"][0].source_type == "layout_key_value"
    assert evidence["gender"][0].evidence_text == "性别：男"
    assert evidence["gender"][0].document_region == "patient_header"


def test_layout_normalizer_derives_split_operation_metadata_key_values():
    profile = load_document_profile()
    document_ir = _document(
        [
            _block("op-title", "手术记录", order=1, bbox=[500, 80, 650, 120]),
            _block("date-label", "手术日期：", order=2, bbox=[100, 150, 190, 175]),
            _block("date-value", "2026年01月12日", order=3, bbox=[360, 150, 520, 175]),
            _block("name-label", "手术名称：", order=4, bbox=[100, 190, 190, 215]),
            _block("name-value", "胆囊癌根治性切除术", order=5, bbox=[360, 190, 620, 215]),
            _block("body", "手术经过顺利。", order=6, bbox=[100, 250, 520, 285]),
        ]
    )

    normalized = normalize_document_layout(document_ir, profile)
    derived = [block for block in normalized.blocks if "layout_neighbor_key_value_pair" in block.quality_flags]
    by_label = {block.key_label: block for block in derived}

    assert by_label["手术日期"].text == "手术日期：2026年01月12日"
    assert by_label["手术日期"].document_region == "operation_metadata"
    assert by_label["手术日期"].derived_from_block_ids == ["date-label", "date-value"]
    assert by_label["手术名称"].text == "手术名称：胆囊癌根治性切除术"


def test_layout_normalizer_derives_key_values_from_same_row_table_cells_without_merging_cells():
    profile = load_document_profile()
    document_ir = _document(
        [
            _block("gender-label", "性别", order=1, bbox=[100, 120, 150, 145]),
            _block("gender-value", "女", order=2, bbox=[160, 120, 190, 145]),
            _block("age-label", "年龄", order=3, bbox=[220, 120, 270, 145]),
            _block("age-value", "42", order=4, bbox=[280, 120, 330, 145]),
        ]
    )
    cells = [
        block.model_copy(
            update={
                "block_type": "cell",
                "table_id": "t-home",
                "row": 1,
                "col": index,
                "section_label": "基本信息",
            }
        )
        for index, block in enumerate(document_ir.blocks, start=1)
    ]
    document_ir = document_ir.model_copy(update={"blocks": cells})

    normalized = normalize_document_layout(document_ir, profile)
    by_id = {block.block_id: block for block in normalized.blocks}
    derived = [block for block in normalized.blocks if "layout_neighbor_key_value_pair" in block.quality_flags]
    by_label = {block.key_label: block for block in derived}

    assert by_id["gender-label"].block_type == "cell"
    assert by_id["gender-value"].block_type == "cell"
    assert "gender-label+gender-value" not in by_id
    assert by_label["性别"].text == "性别：女"
    assert by_label["性别"].derived_from_block_ids == ["gender-label", "gender-value"]
    assert by_label["性别"].bbox == [100.0, 120.0, 190.0, 145.0]
    assert by_label["年龄"].text == "年龄：42"


def test_layout_normalizer_derives_key_values_from_table_header_row_values():
    profile = load_document_profile()
    document_ir = _document(
        [
            _block("h-gender", "性别", order=1, bbox=[100, 100, 150, 125]),
            _block("h-age", "年龄", order=2, bbox=[170, 100, 220, 125]),
            _block("h-case", "病案号", order=3, bbox=[240, 100, 320, 125]),
            _block("v-gender", "男", order=4, bbox=[100, 135, 150, 160]),
            _block("v-age", "58", order=5, bbox=[170, 135, 220, 160]),
            _block("v-case", "A001", order=6, bbox=[240, 135, 320, 160]),
        ]
    )
    cells = [
        block.model_copy(
            update={
                "block_type": "cell",
                "table_id": "t-home",
                "row": 1 if index <= 3 else 2,
                "col": index if index <= 3 else index - 3,
                "section_label": "基本信息",
            }
        )
        for index, block in enumerate(document_ir.blocks, start=1)
    ]
    document_ir = document_ir.model_copy(update={"blocks": cells})

    normalized = normalize_document_layout(document_ir, profile)
    derived = [block for block in normalized.blocks if "layout_table_header_key_value_pair" in block.quality_flags]
    by_label = {block.key_label: block for block in derived}

    assert by_label["性别"].text == "性别：男"
    assert by_label["性别"].derived_from_block_ids == ["h-gender", "v-gender"]
    assert by_label["年龄"].text == "年龄：58"
    assert by_label["病案号"].text == "病案号：A001"


def test_layout_normalizer_derives_key_values_from_spanning_table_group_headers():
    profile = load_document_profile()
    document_ir = _document(
        [
            _block("h-demo", "基本信息", order=1, bbox=[100, 80, 340, 105]),
            _block("h-gender", "性别", order=2, bbox=[100, 112, 150, 137]),
            _block("h-age", "年龄", order=3, bbox=[170, 112, 220, 137]),
            _block("v-gender", "女", order=4, bbox=[100, 145, 150, 170]),
            _block("v-age", "42", order=5, bbox=[170, 145, 220, 170]),
        ]
    )
    cells = [
        document_ir.blocks[0].model_copy(
            update={
                "block_type": "cell",
                "table_id": "t-merged",
                "row": 1,
                "col": 1,
                "col_span": 2,
                "section_label": "基本信息",
            }
        ),
        document_ir.blocks[1].model_copy(update={"block_type": "cell", "table_id": "t-merged", "row": 2, "col": 1, "section_label": "基本信息"}),
        document_ir.blocks[2].model_copy(update={"block_type": "cell", "table_id": "t-merged", "row": 2, "col": 2, "section_label": "基本信息"}),
        document_ir.blocks[3].model_copy(update={"block_type": "cell", "table_id": "t-merged", "row": 3, "col": 1, "section_label": "基本信息"}),
        document_ir.blocks[4].model_copy(update={"block_type": "cell", "table_id": "t-merged", "row": 3, "col": 2, "section_label": "基本信息"}),
    ]
    document_ir = document_ir.model_copy(update={"blocks": cells})

    normalized = normalize_document_layout(document_ir, profile)
    derived = [block for block in normalized.blocks if "layout_table_header_key_value_pair" in block.quality_flags]
    by_label = {block.key_label: block for block in derived}

    assert by_label["性别"].text == "性别：女"
    assert by_label["性别"].derived_from_block_ids == ["h-gender", "v-gender"]
    assert by_label["性别"].bbox == [100.0, 112.0, 150.0, 170.0]
    assert by_label["年龄"].text == "年龄：42"
    assert not any(block.key_label == "基本信息" for block in derived)


def test_layout_normalizer_derives_key_values_from_table_row_header_values():
    profile = load_document_profile()
    document_ir = _document(
        [
            _block("row-label", "mRS", order=1, bbox=[100, 100, 155, 125]),
            _block("value-1", "3", order=2, bbox=[180, 100, 205, 125]),
            _block("value-2", "出院2", order=3, bbox=[230, 100, 290, 125]),
        ]
    )
    cells = [
        block.model_copy(
            update={
                "block_type": "cell",
                "table_id": "t-score",
                "row": 1,
                "col": index,
                "section_label": "评分",
            }
        )
        for index, block in enumerate(document_ir.blocks, start=1)
    ]
    document_ir = document_ir.model_copy(update={"blocks": cells})

    normalized = normalize_document_layout(document_ir, profile)
    derived = [block for block in normalized.blocks if "layout_table_row_header_key_value_pair" in block.quality_flags]

    assert len(derived) == 1
    assert derived[0].text == "mRS：3"
    assert derived[0].derived_from_block_ids == ["row-label", "value-1"]


def test_layout_normalizer_uses_row_span_header_for_later_row_value():
    profile = load_document_profile()
    document_ir = _document(
        [
            _block("row-label", "mRS", order=1, bbox=[100, 100, 155, 165]),
            _block("phase-1", "入院", order=2, bbox=[180, 100, 240, 125]),
            _block("phase-2", "出院", order=3, bbox=[180, 136, 240, 161]),
            _block("score-1", "4", order=4, bbox=[260, 100, 285, 125]),
            _block("score-2", "2", order=5, bbox=[260, 136, 285, 161]),
        ]
    )
    cells = [
        document_ir.blocks[0].model_copy(update={"block_type": "cell", "table_id": "t-score", "row": 1, "col": 1, "row_span": 2, "section_label": "评分"}),
        document_ir.blocks[1].model_copy(update={"block_type": "cell", "table_id": "t-score", "row": 1, "col": 2, "section_label": "评分"}),
        document_ir.blocks[2].model_copy(update={"block_type": "cell", "table_id": "t-score", "row": 2, "col": 2, "section_label": "评分"}),
        document_ir.blocks[3].model_copy(update={"block_type": "cell", "table_id": "t-score", "row": 1, "col": 3, "section_label": "评分"}),
        document_ir.blocks[4].model_copy(update={"block_type": "cell", "table_id": "t-score", "row": 2, "col": 3, "section_label": "评分"}),
    ]
    document_ir = document_ir.model_copy(update={"blocks": cells})

    normalized = normalize_document_layout(document_ir, profile)
    derived = [
        block
        for block in normalized.blocks
        if block.key_label == "mRS" and "layout_table_row_header_key_value_pair" in block.quality_flags
    ]

    assert len(derived) == 2
    assert [block.text for block in derived] == ["mRS：4", "mRS：2"]
    assert derived[1].derived_from_block_ids == ["row-label", "score-2"]


def test_layout_normalizer_merges_wrapped_paragraph_lines_for_cross_line_evidence():
    profile = load_document_profile()
    document_ir = _document(
        [
            _block("history-title", "现病史：", order=1, bbox=[80, 100, 160, 124]),
            _block("history-line-1", "患者主因突发头痛3小时", order=2, bbox=[100, 145, 500, 170]),
            _block("history-line-2", "入院，伴恶心呕吐。", order=3, bbox=[100, 176, 430, 201]),
            _block("history-line-3", "查体配合。", order=4, bbox=[100, 208, 260, 233]),
        ]
    )

    normalized = normalize_document_layout(document_ir, profile)
    paragraphs = [block for block in normalized.blocks if "layout_wrapped_paragraph" in block.quality_flags]

    assert len(paragraphs) == 1
    assert paragraphs[0].text == "患者主因突发头痛3小时入院，伴恶心呕吐。查体配合。"
    assert paragraphs[0].derived_from_block_ids == ["history-line-1", "history-line-2", "history-line-3"]

    context = build_document_context(normalized)
    onset_field = load_extraction_schema().field_by_key("onset_to_admission_time")
    evidence = collect_local_evidence(context, [onset_field])

    assert evidence["onset_to_admission_time"][0].evidence_text == "患者主因突发头痛3小时入院"
    assert evidence["onset_to_admission_time"][0].normalized_code == "3小时"


def test_layout_normalizer_does_not_merge_distant_header_fields():
    profile = load_document_profile()
    document_ir = _document(
        [
            _block("name-label", "姓名：", order=1, bbox=[40, 80, 95, 108]),
            _block("name-value", "王某某", order=2, bbox=[120, 80, 180, 108]),
            _block("address-field", "现住址：", order=3, bbox=[220, 80, 320, 108]),
            _block("gender-field", "性别：男性", order=3, bbox=[40, 118, 150, 146]),
            _block("date-field", "入院日期：2026年04月01日", order=4, bbox=[420, 118, 720, 146]),
            _block("body", "主诉：腹痛伴粘液血便1年，加重6小时。", order=5, bbox=[40, 190, 760, 220]),
        ]
    )

    normalized = normalize_document_layout(document_ir, profile)
    texts = [block.text for block in normalized.blocks]

    assert "姓名：王某某 现住址：" not in texts
    assert any(block.text == "姓名： 王某某" for block in normalized.blocks)
    assert any(block.block_id == "address-field" and block.text == "现住址：" for block in normalized.blocks)
    assert not any(
        "姓名" in block.text and "现住址" in block.text and "layout_merged_line" in block.quality_flags
        for block in normalized.blocks
    )


def test_deidentification_redacts_derived_sensitive_key_value_payloads():
    profile = load_document_profile()
    document_ir = _document(
        [
            _block(
                "header-1",
                "科室：儿科病房  姓名：李某  性别：男  年龄：16  病案号：1266146",
                order=1,
                bbox=[80, 130, 980, 155],
            )
        ]
    )

    normalized = normalize_document_layout(document_ir, profile)
    deidentified = deidentify_document_ir(normalized, profile)
    derived = {
        block.key_label: block
        for block in deidentified.blocks
        if "layout_key_value_pair" in block.quality_flags
    }

    assert derived["姓名"].text == "姓名：[REDACTED]"
    assert derived["姓名"].value_text == "[REDACTED]"
    assert derived["病案号"].text == "病案号：[REDACTED]"
    assert derived["病案号"].value_text == "[REDACTED]"
    assert derived["性别"].text == "性别：男"
    assert derived["性别"].value_text == "男"


def test_field_policy_blocks_demographic_evidence_from_signature_region():
    profile = load_document_profile()
    gender_field = next(field for field in load_extraction_schema().fields if field.key == "gender")
    document_ir = _document(
        [
            _block("title", "病 程 记 录", order=1, bbox=[300, 80, 600, 120]),
            _block("signature", "记录者：性别：女", order=2, bbox=[600, 760, 820, 790]),
        ]
    )
    normalized = normalize_document_layout(document_ir, profile)
    context = build_document_context(normalized)

    evidence = collect_local_evidence(context, [gender_field])
    decisions = adjudicate_field_decisions([gender_field], evidence)

    assert evidence["gender"][0].document_region == "signature"
    assert decisions["gender"].decision_status == "REVIEW"
    assert "document_region_forbidden" in decisions["gender"].review_reasons


def test_layout_normalizer_carries_sections_across_pages_and_classifies_subsections():
    profile = load_document_profile()
    document_ir = _document(
        [
            _block("history-heading", "既往史：", page=1, order=1, bbox=[80, 100, 160, 124]),
            _block("history-body", "否认高血压、糖尿病、冠心病。", page=1, order=2, bbox=[170, 100, 600, 124]),
            _block("next-page", "无药物、食物过敏史。", page=2, order=3, bbox=[80, 80, 560, 105]),
            _block("family-heading", "家族史：父母体健。", page=2, order=4, bbox=[80, 150, 560, 175]),
        ]
    )

    normalized = normalize_document_layout(document_ir, profile)
    by_id = {block.block_id: block for block in normalized.blocks}

    assert by_id["history-heading+history-body"].text == "既往史： 否认高血压、糖尿病、冠心病。"
    assert by_id["history-heading+history-body"].section_label == "既往史"
    assert by_id["next-page"].section_label == "既往史"
    assert by_id["family-heading"].section_label == "家族史"
