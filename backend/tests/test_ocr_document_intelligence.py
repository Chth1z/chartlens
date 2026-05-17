from app.services.ocr_engine.payload_parse import blocks_from_markdown as _blocks_from_markdown
from app.services.ocr_engine.payload_parse import result_from_payload as _result_from_payload


def test_markdown_export_becomes_document_blocks():
    blocks = _blocks_from_markdown("# 入院记录\n\n| 项目 | 结果 |\n| --- | --- |\n| 性别 | 女 |")

    assert [block.text for block in blocks] == ["入院记录", "| 项目 | 结果 |", "| 性别 | 女 |"]
    assert blocks[0].block_type == "text"
    assert blocks[1].block_type == "table"


def test_paddle_payload_preserves_structured_cells():
    result = _result_from_payload(
        "paddleocr_vl",
        {
            "page": 1,
            "layout": [
                {
                    "text": "手术名称",
                    "bbox": [10, 20, 80, 40],
                    "score": 0.91,
                    "type": "cell",
                    "table_id": "table-1",
                    "row": 1,
                    "col": 1,
                    "rowSpan": 2,
                    "colSpan": 3,
                }
            ],
        },
        default_confidence=0.88,
    )

    assert result.engine == "paddleocr_vl"
    assert len(result.blocks) == 1
    assert result.blocks[0].block_type == "cell"
    assert result.blocks[0].table_id == "table-1"
    assert result.blocks[0].row == 1
    assert result.blocks[0].col == 1
    assert result.blocks[0].row_span == 2
    assert result.blocks[0].col_span == 3
