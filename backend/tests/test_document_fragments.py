from app.schemas.pipeline import OcrBlock
from app.services.document_fragments import build_document_fragments, summarize_ocr_quality


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
