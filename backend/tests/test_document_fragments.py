from app.domain.clinical import OcrBlock
from app.application.document_fragments import build_document_fragments, summarize_ocr_quality


def test_document_fragments_assign_sections_and_reading_order():
    blocks = [
        OcrBlock(page=1, text="基本信息：性别：女 年龄：66岁", bbox=[0, 10, 500, 28], confidence=0.96),
        OcrBlock(page=1, text="既往史：否认高血压病史，否认糖尿病病史。", bbox=[0, 40, 780, 58], confidence=0.88),
        OcrBlock(page=2, text="出院情况：好转出院。", bbox=[0, 12, 500, 30], confidence=0.72),
    ]

    fragments = build_document_fragments(blocks)

    paragraphs = [fragment for fragment in fragments if fragment.block_type == "paragraph"]
    assert [fragment.reading_order for fragment in paragraphs] == [1, 2, 3]
    assert paragraphs[0].section_name == "基本信息"
    assert paragraphs[1].section_name == "既往史"
    assert paragraphs[2].section_name == "出院情况"
    assert paragraphs[2].source_kind == "ocr"


def test_section_detection_handles_numbered_headings_and_avoids_history_informant():
    blocks = [
        OcrBlock(page=1, text="病史陈述人：小红本人", bbox=[0, 10, 500, 28], confidence=0.96),
        OcrBlock(page=1, text="一、既往史：否认高血压、糖尿病。", bbox=[0, 40, 780, 58], confidence=0.88),
        OcrBlock(page=1, text="（三）个人史：不吸烟，不饮酒。", bbox=[0, 70, 780, 88], confidence=0.92),
    ]

    paragraphs = [fragment for fragment in build_document_fragments(blocks) if fragment.block_type == "paragraph"]

    assert paragraphs[0].section_name == "基本信息"
    assert paragraphs[1].section_name == "既往史"
    assert paragraphs[2].section_name == "个人史"


def test_section_detection_handles_common_chinese_discharge_record_titles():
    blocks = [
        OcrBlock(page=1, text="住院病案首页：姓名张三 性别男 年龄66岁", bbox=[0, 10, 720, 28], confidence=0.95),
        OcrBlock(page=2, text="出院记录：患者神志清，病情好转出院。", bbox=[0, 40, 760, 58], confidence=0.93),
        OcrBlock(page=2, text="诊疗经过：行介入栓塞术，术后恢复可。", bbox=[0, 70, 760, 88], confidence=0.92),
    ]

    paragraphs = [fragment for fragment in build_document_fragments(blocks) if fragment.block_type == "paragraph"]

    assert paragraphs[0].section_name == "基本信息"
    assert paragraphs[1].section_name == "出院情况"
    assert paragraphs[2].section_name == "出院情况"


def test_homepage_form_fields_are_extracted_as_high_priority_fragments():
    blocks = [
        OcrBlock(page=1, text="大病历书写（参考10版诊断学教材）", bbox=[0, 10, 700, 28], confidence=0.89),
        OcrBlock(page=1, text="姓名：小红 住址：A省B市C区XXXX路1号", bbox=[0, 40, 700, 58], confidence=0.84),
        OcrBlock(page=1, text="性别：女 联系人：小明", bbox=[0, 70, 700, 88], confidence=0.86),
        OcrBlock(page=1, text="年龄：60岁 工作单位：无", bbox=[0, 100, 700, 118], confidence=0.87),
        OcrBlock(page=1, text="职业：退休人员 病史陈述人：小红本人 可靠程度：可靠", bbox=[0, 130, 700, 148], confidence=0.83),
    ]

    fragments = build_document_fragments(blocks)
    form_fields = [fragment for fragment in fragments if fragment.block_type == "form_field"]

    assert [fragment.text for fragment in form_fields] == [
        "姓名：小红",
        "住址：A省B市C区XXXX路1号",
        "性别：女",
        "联系人：小明",
        "年龄：60岁",
        "工作单位：无",
        "职业：退休人员",
        "病史陈述人：小红本人",
        "可靠程度：可靠",
    ]
    assert all(fragment.section_name == "基本信息" for fragment in form_fields)
    assert min(fragment.confidence for fragment in form_fields) >= 0.90
    by_text = {fragment.text: fragment for fragment in form_fields}
    assert by_text["姓名：小红"].bbox[2] <= by_text["住址：A省B市C区XXXX路1号"].bbox[0]
    assert by_text["性别：女"].bbox[2] <= by_text["联系人：小明"].bbox[0]
    assert by_text["职业：退休人员"].bbox[2] <= by_text["病史陈述人：小红本人"].bbox[0]


def test_homepage_form_fields_pair_adjacent_label_and_value_blocks():
    blocks = [
        OcrBlock(page=1, text="性别：", bbox=[120, 70, 170, 88], confidence=0.86),
        OcrBlock(page=1, text="女", bbox=[185, 70, 205, 88], confidence=0.86),
        OcrBlock(page=1, text="联系人：小明", bbox=[380, 70, 520, 88], confidence=0.86),
        OcrBlock(page=1, text="年龄：", bbox=[120, 100, 170, 118], confidence=0.87),
        OcrBlock(page=1, text="60岁", bbox=[185, 100, 230, 118], confidence=0.87),
        OcrBlock(page=1, text="工作单位：无", bbox=[380, 100, 520, 118], confidence=0.87),
    ]

    fragments = build_document_fragments(blocks)
    form_field_fragments = [fragment for fragment in fragments if fragment.block_type == "form_field"]
    form_fields = [fragment.text for fragment in form_field_fragments]

    assert "性别：女" in form_fields
    assert "年龄：60岁" in form_fields
    assert "性别：" not in form_fields
    assert "年龄：" not in form_fields
    by_text = {fragment.text: fragment for fragment in form_field_fragments}
    assert by_text["性别：女"].bbox == [120, 70, 205, 88]
    assert by_text["年龄：60岁"].bbox == [120, 100, 230, 118]


def test_standalone_headings_do_not_get_swallowed_by_previous_short_section():
    blocks = [
        OcrBlock(page=6, text="辅助检查", bbox=[320, 10, 430, 30], confidence=0.73),
        OcrBlock(page=6, text="暂缺。", bbox=[20, 45, 100, 65], confidence=0.78),
        OcrBlock(page=6, text="病例摘要", bbox=[320, 95, 430, 115], confidence=0.89),
        OcrBlock(page=6, text="患者：小红，老年女性患者，急性病程。", bbox=[20, 140, 760, 158], confidence=0.89),
        OcrBlock(page=6, text="初步诊断", bbox=[320, 260, 430, 280], confidence=0.86),
        OcrBlock(page=6, text="1.发热查因：肺炎？", bbox=[20, 305, 300, 323], confidence=0.86),
        OcrBlock(page=6, text="医师签名：LDM", bbox=[300, 370, 470, 388], confidence=0.86),
    ]

    paragraphs = [fragment for fragment in build_document_fragments(blocks) if fragment.block_type == "paragraph"]
    titles = [fragment for fragment in build_document_fragments(blocks) if fragment.block_type == "title"]

    assert [title.text for title in titles] == ["辅助检查", "病例摘要", "初步诊断"]
    assert [paragraph.section_name for paragraph in paragraphs] == ["辅助检查", "现病史", "入院诊断", "入院诊断"]


def test_paragraph_fragments_merge_wrapped_lines_within_section():
    blocks = [
        OcrBlock(page=1, text="现病史：患者于10余天前无明显诱因出现发热，体温最高", bbox=[0, 10, 700, 28], confidence=0.94),
        OcrBlock(page=1, text="37.6℃，伴肢体乏力，伴恶心，无明显咳嗽、咳痰，", bbox=[0, 32, 700, 50], confidence=0.93),
        OcrBlock(page=1, text="无腹泻，无午后潮热、盗汗。于当地私人诊所就诊输液治疗（具体不", bbox=[0, 54, 700, 72], confidence=0.91),
        OcrBlock(page=1, text="详），症状反复。", bbox=[0, 76, 220, 94], confidence=0.91),
        OcrBlock(page=1, text="既往史：否认高血压。", bbox=[0, 120, 500, 138], confidence=0.90),
    ]

    paragraphs = [fragment for fragment in build_document_fragments(blocks) if fragment.block_type == "paragraph"]

    assert len(paragraphs) == 2
    assert paragraphs[0].section_name == "现病史"
    assert "具体不详" in paragraphs[0].text
    assert paragraphs[1].section_name == "既往史"


def test_ocr_quality_summary_tracks_low_confidence_pages():
    blocks = [
        OcrBlock(page=1, text="性别：男", bbox=[0, 0, 80, 20], confidence=0.98),
        OcrBlock(page=2, text="模糊文本", bbox=[0, 0, 80, 20], confidence=0.52),
    ]
    fragments = build_document_fragments(blocks)

    summary = summarize_ocr_quality(blocks, fragments)

    assert summary.page_count == 2
    assert summary.ocr_block_count == 2
    assert summary.fragment_count == 2
    assert summary.low_confidence_block_count == 1
    assert summary.quality_band == "fair"
