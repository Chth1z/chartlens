from __future__ import annotations

from app.core.config_loader import load_ocr_profile
from app.services.ocr_engine import IntelligentOcrBlock, IntelligentOcrResult
from app.services.ocr_engine.canonicalize import _merge_hybrid_ocr_results


def test_hybrid_merge_keeps_stage_candidates_and_conflict_flags():
    base_profile = load_ocr_profile("windows_radeon_balanced")
    profile = base_profile.model_copy(
        update={
            "pipeline_stages": ["preprocess", "paddleocr_vl", "pp_structure_v3", "pp_ocr_v5", "merge"],
            "stage_models": {
                **base_profile.stage_models,
                "pp_structure_v3": {"engine_id": "paddle_structure_v3", "enabled": True, "required": False},
            },
        }
    )
    stage_results = {
        "paddleocr_vl": IntelligentOcrResult(
            engine="paddleocr_vl",
            blocks=[IntelligentOcrBlock(page=1, text="白细胞 8.6", bbox=[0, 0, 100, 20], confidence=0.91, block_type="cell", table_id="t1", row=1, col=2)],
            metadata={"model_name": "PaddleOCR-VL-1.5", "model_version": "1.5", "raw_markdown": "|白细胞|8.6|"},
        ),
        "pp_structure_v3": IntelligentOcrResult(
            engine="paddle_structure_v3",
            blocks=[IntelligentOcrBlock(page=1, text="白细胞 8.8", bbox=[0, 0, 100, 20], confidence=0.89, block_type="cell", table_id="t1", row=1, col=2)],
            metadata={"model_name": "PP-StructureV3"},
        ),
        "pp_ocr_v5": IntelligentOcrResult(
            engine="pp_ocr_v5_onnx_directml",
            blocks=[IntelligentOcrBlock(page=1, text="白细胞 8.6", bbox=[0, 0, 100, 20], confidence=0.97, block_type="text")],
            metadata={"model_name": "PP-OCRv5", "accelerator": "directml"},
        ),
    }

    result = _merge_hybrid_ocr_results(stage_results, profile=profile)

    assert result.engine == "paddleocr_hybrid"
    assert result.metadata["canonical_blocks_version"] == "ocr-canonical-layout-v3"
    assert result.metadata["pipeline_stages"] == profile.pipeline_stages
    assert set(result.metadata["stage_metrics"]) >= {"paddleocr_vl", "pp_structure_v3", "pp_ocr_v5"}
    assert result.metadata["candidate_sets"]["paddleocr_vl"][0]["text"] == "白细胞 8.6"
    assert result.metadata["candidate_sets"]["pp_structure_v3"][0]["text"] == "白细胞 8.8"
    assert result.metadata["raw_candidates"]["pp_ocr_v5"][0]["text"] == "白细胞 8.6"
    assert result.metadata["raw_markdown"] == "|白细胞|8.6|"
    table_cells = [block for block in result.blocks if block.table_id == "t1" and block.row == 1 and block.col == 2]
    assert len(table_cells) == 1
    assert table_cells[0].stage_source == "paddleocr_vl"
    assert "pp_structure_v3" in table_cells[0].conflict_flags
    assert "pp_ocr_v5" in table_cells[0].conflict_flags
    assert table_cells[0].canonical_source_ids
    assert all(block.candidate_id for block in result.blocks)
    assert all(block.candidate_group_id for block in result.blocks)
    assert all("text_conflict" in block.conflict_flags for block in table_cells)


def test_hybrid_merge_rebuilds_canonical_order_from_layout_geometry_not_raw_stage_order():
    base_profile = load_ocr_profile("windows_radeon_balanced")
    profile = base_profile.model_copy(
        update={
            "pipeline_stages": ["preprocess", "paddleocr_vl", "pp_structure_v3", "pp_ocr_v5", "merge"],
            "stage_models": {
                **base_profile.stage_models,
                "paddleocr_vl": {"engine_id": "paddleocr_vl_remote", "enabled": True, "required": True},
                "pp_structure_v3": {"engine_id": "paddle_structure_v3", "enabled": True, "required": True},
            },
        }
    )
    stage_results = {
        "paddleocr_vl": IntelligentOcrResult(
            engine="paddleocr_vl_remote",
            blocks=[
                IntelligentOcrBlock(page=1, text="口：无口臭，唇淡红色。", bbox=[90, 320, 700, 350], confidence=0.94),
                IntelligentOcrBlock(page=1, text="颈部：颈外观对称，无抵抗。", bbox=[90, 420, 760, 450], confidence=0.95),
                IntelligentOcrBlock(page=1, text="胸部：胸廓对称，无畸形。", bbox=[90, 520, 760, 550], confidence=0.95),
            ],
            metadata={"model_name": "PaddleOCR-VL-1.5"},
        ),
        "pp_ocr_v5": IntelligentOcrResult(
            engine="pp_ocr_v5_onnx_directml",
            blocks=[
                IntelligentOcrBlock(page=1, text="胸部：胸廓对称，无畸形。", bbox=[90, 520, 760, 550], confidence=0.99),
                IntelligentOcrBlock(page=1, text="口：无口臭，唇淡红色。", bbox=[90, 320, 700, 350], confidence=0.99),
                IntelligentOcrBlock(page=1, text="颈部：颈外观对称，无抵抗。", bbox=[90, 420, 760, 450], confidence=0.99),
            ],
            metadata={"model_name": "PP-OCRv5", "accelerator": "directml"},
        ),
        "pp_structure_v3": IntelligentOcrResult(
            engine="paddle_structure_v3",
            blocks=[
                IntelligentOcrBlock(page=1, text="口：无口臭，唇淡红色。", bbox=[88, 318, 702, 352], confidence=0.93),
                IntelligentOcrBlock(page=1, text="颈部：颈外观对称，无抵抗。", bbox=[88, 418, 762, 452], confidence=0.93),
                IntelligentOcrBlock(page=1, text="胸部：胸廓对称，无畸形。", bbox=[88, 518, 762, 552], confidence=0.93),
            ],
            metadata={"model_name": "PP-StructureV3"},
        ),
    }

    result = _merge_hybrid_ocr_results(stage_results, profile=profile)

    assert [block.text for block in result.blocks] == [
        "口：无口臭，唇淡红色。",
        "颈部：颈外观对称，无抵抗。",
        "胸部：胸廓对称，无畸形。",
    ]
    assert [region["text"] for region in result.metadata["layout_regions"]] == [
        "口：无口臭，唇淡红色。",
        "颈部：颈外观对称，无抵抗。",
        "胸部：胸廓对称，无畸形。",
    ]
    assert result.metadata["order_metrics"]["canonical_block_count"] == 3
    assert result.metadata["order_metrics"]["suppressed_candidate_count"] >= 6


def test_hybrid_merge_sorts_same_row_cells_left_to_right_despite_y_jitter():
    profile = load_ocr_profile("windows_radeon_balanced")
    stage_results = {
        "pp_ocr_v5": IntelligentOcrResult(
            engine="pp_ocr_v5_onnx_directml",
            blocks=[
                IntelligentOcrBlock(page=1, text="结果", bbox=[360, 462, 430, 504], confidence=0.99),
                IntelligentOcrBlock(page=1, text="单位", bbox=[560, 462, 625, 505], confidence=0.99),
                IntelligentOcrBlock(page=1, text="检验项目", bbox=[112, 463, 216, 501], confidence=0.99),
                IntelligentOcrBlock(page=1, text="参考范围", bbox=[753, 463, 860, 505], confidence=0.99),
            ],
            metadata={"model_name": "PP-OCRv5", "accelerator": "directml"},
        )
    }

    result = _merge_hybrid_ocr_results(stage_results, profile=profile)

    assert [block.text for block in result.blocks] == ["检验项目", "结果", "单位", "参考范围"]


def test_hybrid_merge_recovers_table_cells_from_aligned_ocr_text_geometry():
    profile = load_ocr_profile("windows_radeon_balanced")
    stage_results = {
        "pp_ocr_v5": IntelligentOcrResult(
            engine="pp_ocr_v5_onnx_directml",
            blocks=[
                IntelligentOcrBlock(page=1, text="Test", bbox=[132, 325, 183, 344], confidence=0.99),
                IntelligentOcrBlock(page=1, text="Result", bbox=[292, 325, 366, 344], confidence=0.99),
                IntelligentOcrBlock(page=1, text="Unit", bbox=[442, 325, 489, 344], confidence=0.99),
                IntelligentOcrBlock(page=1, text="Flag", bbox=[602, 325, 652, 349], confidence=0.99),
                IntelligentOcrBlock(page=1, text="WBC", bbox=[132, 365, 193, 384], confidence=0.99),
                IntelligentOcrBlock(page=1, text="8.6", bbox=[292, 365, 327, 384], confidence=0.99),
                IntelligentOcrBlock(page=1, text="10^9/L", bbox=[442, 365, 517, 384], confidence=0.99),
                IntelligentOcrBlock(page=1, text="normal", bbox=[602, 365, 681, 384], confidence=0.99),
                IntelligentOcrBlock(page=1, text="CRP", bbox=[132, 405, 187, 424], confidence=0.99),
                IntelligentOcrBlock(page=1, text="3.2", bbox=[292, 405, 327, 424], confidence=0.99),
                IntelligentOcrBlock(page=1, text="mg/L", bbox=[442, 405, 499, 429], confidence=0.99),
                IntelligentOcrBlock(page=1, text="normal", bbox=[602, 405, 681, 424], confidence=0.99),
            ],
            metadata={"model_name": "PP-OCRv5", "accelerator": "directml"},
        )
    }

    result = _merge_hybrid_ocr_results(stage_results, profile=profile)

    cells = [block for block in result.blocks if block.block_type == "cell"]
    assert len(cells) == 12
    assert [(cell.text, cell.row, cell.col) for cell in cells[:4]] == [
        ("Test", 1, 1),
        ("Result", 1, 2),
        ("Unit", 1, 3),
        ("Flag", 1, 4),
    ]
    assert cells[0].table_id == cells[-1].table_id
    assert cells[0].bbox == [120.0, 313.0, 280.0, 353.0]
    assert cells[5].bbox == [280.0, 353.0, 430.0, 393.0]
    assert result.metadata["tables"] == [
        {
            "table_id": cells[0].table_id,
            "page": 1,
            "cell_count": 12,
            "stage_sources": ["pp_ocr_v5"],
        }
    ]
    assert result.metadata["cells"][0]["row"] == 1
    assert result.metadata["cells"][0]["col"] == 1


def test_hybrid_merge_orders_inferred_table_before_lower_paragraph():
    profile = load_ocr_profile("windows_radeon_balanced")
    stage_results = {
        "pp_ocr_v5": IntelligentOcrResult(
            engine="pp_ocr_v5_onnx_directml",
            blocks=[
                IntelligentOcrBlock(page=1, text="Test", bbox=[132, 325, 183, 344], confidence=0.99),
                IntelligentOcrBlock(page=1, text="Result", bbox=[292, 325, 366, 344], confidence=0.99),
                IntelligentOcrBlock(page=1, text="Unit", bbox=[442, 325, 489, 344], confidence=0.99),
                IntelligentOcrBlock(page=1, text="Flag", bbox=[602, 325, 652, 349], confidence=0.99),
                IntelligentOcrBlock(page=1, text="WBC", bbox=[132, 365, 193, 384], confidence=0.99),
                IntelligentOcrBlock(page=1, text="8.6", bbox=[292, 365, 327, 384], confidence=0.99),
                IntelligentOcrBlock(page=1, text="10^9/L", bbox=[442, 365, 517, 384], confidence=0.99),
                IntelligentOcrBlock(page=1, text="normal", bbox=[602, 365, 681, 384], confidence=0.99),
                IntelligentOcrBlock(page=1, text="CRP", bbox=[132, 405, 187, 424], confidence=0.99),
                IntelligentOcrBlock(page=1, text="3.2", bbox=[292, 405, 327, 424], confidence=0.99),
                IntelligentOcrBlock(page=1, text="mg/L", bbox=[442, 405, 499, 429], confidence=0.99),
                IntelligentOcrBlock(page=1, text="normal", bbox=[602, 405, 681, 424], confidence=0.99),
                IntelligentOcrBlock(
                    page=1,
                    text="Synthetic only. Contains no PHI and no real patient data.",
                    bbox=[120, 494, 624, 513],
                    confidence=0.99,
                ),
            ],
            metadata={"model_name": "PP-OCRv5", "accelerator": "directml"},
        )
    }

    result = _merge_hybrid_ocr_results(stage_results, profile=profile)

    assert [block.text for block in result.blocks] == [
        "Test",
        "Result",
        "Unit",
        "Flag",
        "WBC",
        "8.6",
        "10^9/L",
        "normal",
        "CRP",
        "3.2",
        "mg/L",
        "normal",
        "Synthetic only. Contains no PHI and no real patient data.",
    ]
