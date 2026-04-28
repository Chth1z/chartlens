from app.schemas.pipeline import OcrBlock
from app.services.ocr_postprocess import postprocess_ocr_blocks


def test_postprocess_splits_compound_medical_key_value_lines():
    blocks = [
        OcrBlock(
            page=1,
            text="性别：男 年龄：66岁 出院情况：好转出院。",
            bbox=[0.0, 0.0, 300.0, 24.0],
            confidence=0.93,
        )
    ]

    processed = postprocess_ocr_blocks(blocks)

    assert [block.text for block in processed] == ["性别：男", "年龄：66岁", "出院情况：好转出院。"]
    assert all(block.page == 1 for block in processed)


def test_postprocess_splits_ocr_lines_with_adjacent_history_labels():
    blocks = [
        OcrBlock(
            page=1,
            text="职业：退休人员病史陈述人：本人可靠程度：可靠",
            bbox=[0.0, 0.0, 360.0, 24.0],
            confidence=0.86,
        )
    ]

    processed = postprocess_ocr_blocks(blocks)

    assert [block.text for block in processed] == ["职业：退休人员", "病史陈述人：本人", "可靠程度：可靠"]
