from app.application.document_fragments import build_document_fragments
from app.application.layout_analysis import SECTION_CLASSIFIER_VERSION, fallback_regions_from_blocks
from app.domain.clinical import LayoutRegion, OcrBlock


def test_layout_regions_control_reading_order_and_metadata():
    blocks = [
        OcrBlock(page=1, text="右栏：住院号：[住院号]", bbox=[420, 20, 760, 40], confidence=0.92),
        OcrBlock(page=1, text="左栏：科别：传染科", bbox=[80, 120, 360, 140], confidence=0.92),
    ]
    regions = [
        LayoutRegion(page=1, region_id="left", bbox=[60, 100, 380, 180], region_type="text", score=0.91, reading_order=1),
        LayoutRegion(page=1, region_id="right", bbox=[400, 10, 780, 80], region_type="text", score=0.91, reading_order=2),
    ]

    paragraphs = [
        fragment
        for fragment in build_document_fragments(blocks, layout_regions=regions)
        if fragment.block_type == "paragraph"
    ]

    assert [fragment.text for fragment in paragraphs] == ["左栏：科别：传染科", "右栏：住院号：[住院号]"]
    assert paragraphs[0].layout_region_id == "left"
    assert paragraphs[0].layout_type == "text"
    assert paragraphs[0].section_confidence >= 0.5
    assert paragraphs[0].parser_version.startswith("hybrid_layout")


def test_low_confidence_unclassified_region_stays_unknown_section():
    blocks = [
        OcrBlock(page=3, text="不明确的孤立文本", bbox=[50, 50, 250, 70], confidence=0.70),
    ]
    regions = [
        LayoutRegion(page=3, region_id="ambiguous", bbox=[40, 40, 300, 100], region_type="text", score=0.25, reading_order=1),
    ]

    paragraphs = [
        fragment
        for fragment in build_document_fragments(blocks, layout_regions=regions)
        if fragment.block_type == "paragraph"
    ]

    assert paragraphs[0].section_name == "unknown_section"
    assert paragraphs[0].section_confidence < 0.5
    assert paragraphs[0].parser_version.endswith(SECTION_CLASSIFIER_VERSION)


def test_fallback_layout_keeps_wrapped_medical_content_in_one_paragraph():
    blocks = [
        OcrBlock(page=1, text="既往史 体质一般，平时易出汗，有“婴儿湿疹”史。4个月时因“支", bbox=[80, 560, 720, 582], confidence=0.93),
        OcrBlock(page=1, text="气管炎”在我院治疗8天好转出院。否认结核、麻疹等传染病史。", bbox=[80, 588, 720, 610], confidence=0.93),
        OcrBlock(page=1, text="个人史", bbox=[80, 660, 160, 682], confidence=0.95),
        OcrBlock(page=1, text="出生史：G1P1，孕38周顺产。", bbox=[80, 704, 600, 726], confidence=0.94),
    ]

    paragraphs = [
        fragment
        for fragment in build_document_fragments(blocks, layout_regions=fallback_regions_from_blocks(blocks))
        if fragment.block_type == "paragraph"
    ]

    assert len(paragraphs) == 2
    assert paragraphs[0].section_name == "既往史"
    assert "支气管炎" in paragraphs[0].text
    assert paragraphs[0].layout_region_id == "fallback-p1-content"
    assert paragraphs[1].section_name == "个人史"
