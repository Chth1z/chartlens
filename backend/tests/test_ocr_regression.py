from __future__ import annotations

from app.core.config_loader import (
    load_ocr_evaluation_profile,
    read_config_artifact,
    validate_ocr_evaluation_profiles,
    validate_project_config,
)
from app.core.settings import settings
from app.domain.models import DocumentIR, DocumentIRBlock
from app.services.ocr_engine.evaluation import evaluate_layout_tables
from app.services.ocr_engine.types import IntelligentOcrBlock, IntelligentOcrResult
from app.services.ocr_engine.canonicalize import _merge_hybrid_ocr_results
from app.services.ocr_engine.regression import run_ocr_evaluation_profile


def test_layout_table_metrics_match_blocks_by_text_bbox_order_and_cells():
    document_ir = DocumentIR(
        document_id="synthetic-layout",
        profile_id="medical_inpatient_zh",
        source_filename="synthetic.pdf",
        blocks=[
            DocumentIRBlock(
                block_id="b1",
                page=1,
                reading_order=1,
                text="基本信息：患者，男，66岁。",
                bbox=[122, 91, 858, 129],
                confidence=0.96,
                block_type="paragraph",
            ),
            DocumentIRBlock(
                block_id="b2",
                page=1,
                reading_order=2,
                text="白细胞",
                bbox=[121, 181, 219, 209],
                confidence=0.95,
                block_type="cell",
                table_id="t1",
                row=2,
                col=1,
            ),
            DocumentIRBlock(
                block_id="b3",
                page=1,
                reading_order=3,
                text="8.6",
                bbox=[241, 181, 299, 209],
                confidence=0.95,
                block_type="cell",
                table_id="t1",
                row=2,
                col=2,
            ),
        ],
    )
    truth_blocks = [
        {"page": 1, "reading_order": 1, "text": "基本信息：患者，男，66岁。", "bbox": [120, 90, 860, 130]},
        {"page": 1, "reading_order": 2, "text": "白细胞", "bbox": [120, 180, 220, 210]},
    ]
    truth_tables = [
        {
            "table_id": "t1",
            "page": 1,
            "cells": [
                {"row": 2, "col": 1, "text": "白细胞", "bbox": [120, 180, 220, 210]},
                {"row": 2, "col": 2, "text": "8.6", "bbox": [240, 180, 300, 210]},
            ],
        }
    ]

    metrics = evaluate_layout_tables(document_ir, truth_blocks, truth_tables)

    assert metrics["truth_block_count"] == 2
    assert metrics["matched_block_count"] == 2
    assert metrics["block_text_match_accuracy"] == 1.0
    assert metrics["block_bbox_iou_accuracy"] == 1.0
    assert metrics["block_center_accuracy"] == 1.0
    assert metrics["reading_order_accuracy"] == 1.0
    assert metrics["truth_table_cell_count"] == 2
    assert metrics["matched_table_cell_count"] == 2
    assert metrics["table_cell_text_accuracy"] == 1.0
    assert metrics["table_cell_key_accuracy"] == 1.0
    assert metrics["table_cell_bbox_accuracy"] == 1.0


def test_layout_table_metrics_penalize_misordered_and_misplaced_predictions():
    document_ir = DocumentIR(
        document_id="synthetic-layout-miss",
        profile_id="medical_inpatient_zh",
        source_filename="synthetic.pdf",
        blocks=[
            DocumentIRBlock(
                block_id="b1",
                page=1,
                reading_order=2,
                text="基本信息：患者，男，66岁。",
                bbox=[500, 500, 900, 540],
                confidence=0.96,
            ),
            DocumentIRBlock(
                block_id="b2",
                page=1,
                reading_order=1,
                text="白细胞",
                bbox=[120, 180, 220, 210],
                confidence=0.95,
                block_type="cell",
                table_id="t1",
                row=2,
                col=2,
            ),
        ],
    )

    metrics = evaluate_layout_tables(
        document_ir,
        [
            {"page": 1, "reading_order": 1, "text": "基本信息：患者，男，66岁。", "bbox": [120, 90, 860, 130]},
            {"page": 1, "reading_order": 2, "text": "白细胞", "bbox": [120, 180, 220, 210]},
        ],
        [
            {
                "table_id": "t1",
                "page": 1,
                "cells": [{"row": 2, "col": 1, "text": "白细胞", "bbox": [120, 180, 220, 210]}],
            }
        ],
    )

    assert metrics["matched_block_count"] == 2
    assert metrics["block_text_match_accuracy"] == 1.0
    assert metrics["block_bbox_iou_accuracy"] == 0.5
    assert metrics["block_center_accuracy"] == 0.5
    assert metrics["reading_order_accuracy"] == 0.0
    assert metrics["table_cell_text_accuracy"] == 1.0
    assert metrics["table_cell_key_accuracy"] == 0.0


def test_layout_table_metrics_score_inferred_grid_cells_from_ocr_text_geometry():
    from app.core.config_loader import load_ocr_profile
    from app.services.ocr_engine.engine_base import _blocks_from_intelligent_result

    profile = load_ocr_profile("windows_radeon_balanced")
    result = _merge_hybrid_ocr_results(
        {
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
        },
        profile=profile,
    )
    document_ir = DocumentIR(
        document_id="synthetic-grid",
        profile_id="medical_inpatient_zh",
        source_filename="synthetic.png",
        blocks=_blocks_from_intelligent_result(result, {}, document_profile=None),
    )

    metrics = evaluate_layout_tables(
        document_ir,
        [],
        [
            {
                "table_id": "synthetic_labs",
                "page": 1,
                "cells": [
                    {"row": 1, "col": 1, "text": "Test", "bbox": [120, 313, 280, 353]},
                    {"row": 1, "col": 2, "text": "Result", "bbox": [280, 313, 430, 353]},
                    {"row": 1, "col": 3, "text": "Unit", "bbox": [430, 313, 590, 353]},
                    {"row": 1, "col": 4, "text": "Flag", "bbox": [590, 313, 740, 353]},
                    {"row": 2, "col": 1, "text": "WBC", "bbox": [120, 353, 280, 393]},
                    {"row": 2, "col": 2, "text": "8.6", "bbox": [280, 353, 430, 393]},
                    {"row": 2, "col": 3, "text": "10^9/L", "bbox": [430, 353, 590, 393]},
                    {"row": 2, "col": 4, "text": "normal", "bbox": [590, 353, 740, 393]},
                    {"row": 3, "col": 1, "text": "CRP", "bbox": [120, 393, 280, 433]},
                    {"row": 3, "col": 2, "text": "3.2", "bbox": [280, 393, 430, 433]},
                    {"row": 3, "col": 3, "text": "mg/L", "bbox": [430, 393, 590, 433]},
                    {"row": 3, "col": 4, "text": "normal", "bbox": [590, 393, 740, 433]},
                ],
            }
        ],
    )

    assert metrics["matched_table_cell_count"] == 12
    assert metrics["table_cell_text_accuracy"] == 1.0
    assert metrics["table_cell_key_accuracy"] == 1.0
    assert metrics["table_cell_bbox_accuracy"] == 1.0


def test_layout_table_metrics_evaluate_inferred_cells_against_structural_block_truth():
    document_ir = DocumentIR(
        document_id="synthetic-structural-cells",
        profile_id="medical_inpatient_zh",
        source_filename="synthetic.png",
        blocks=[
            DocumentIRBlock(
                block_id="title",
                page=1,
                reading_order=1,
                text="EYEX SYNTHETIC OCR EVAL",
                bbox=[121, 74, 599, 104],
                confidence=0.99,
                block_type="text",
            ),
            DocumentIRBlock(
                block_id="test",
                page=1,
                reading_order=2,
                text="Test",
                bbox=[112, 303, 274, 345],
                confidence=0.99,
                block_type="cell",
                table_id="inferred-grid-p1-1",
                row=1,
                col=1,
            ),
        ],
    )

    metrics = evaluate_layout_tables(
        document_ir,
        [
            {"page": 1, "reading_order": 1, "text": "EYEX SYNTHETIC OCR EVAL", "bbox": [120, 78, 598, 103]},
            {"page": 1, "reading_order": 2, "text": "Test", "bbox": [120, 313, 280, 353], "row": 1, "col": 1},
        ],
        [
            {
                "table_id": "synthetic_labs",
                "page": 1,
                "cells": [{"row": 1, "col": 1, "text": "Test", "bbox": [120, 313, 280, 353]}],
            }
        ],
    )

    assert metrics["matched_block_count"] == 2
    assert metrics["block_bbox_iou_accuracy"] == 1.0
    assert metrics["block_center_accuracy"] == 1.0
    assert metrics["reading_order_accuracy"] == 1.0
    assert metrics["table_cell_bbox_accuracy"] == 1.0


def test_recovered_grid_cells_preserve_row_major_reading_order_for_repeated_text():
    from app.core.config_loader import load_ocr_profile
    from app.services.ocr_engine.engine_base import _blocks_from_intelligent_result

    profile = load_ocr_profile("windows_radeon_balanced")
    result = _merge_hybrid_ocr_results(
        {
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
        },
        profile=profile,
    )
    document_blocks = _blocks_from_intelligent_result(result, {}, document_profile=None)

    assert [(block.reading_order, block.text) for block in document_blocks] == [
        (1, "Test"),
        (2, "Result"),
        (3, "Unit"),
        (4, "Flag"),
        (5, "WBC"),
        (6, "8.6"),
        (7, "10^9/L"),
        (8, "normal"),
        (9, "CRP"),
        (10, "3.2"),
        (11, "mg/L"),
        (12, "normal"),
    ]


def test_structured_grid_cells_preserve_row_major_reading_order_when_rows_share_band():
    from app.core.config_loader import load_ocr_profile
    from app.services.ocr_engine.engine_base import _blocks_from_intelligent_result

    profile = load_ocr_profile("windows_radeon_balanced")
    result = _merge_hybrid_ocr_results(
        {
            "pp_ocr_v5": IntelligentOcrResult(
                engine="pp_ocr_v5_onnx_directml",
                blocks=[
                    IntelligentOcrBlock(page=1, text="WBC", bbox=[112, 345, 274, 385], confidence=0.99, block_type="cell", table_id="t1", row=2, col=1),
                    IntelligentOcrBlock(page=1, text="CRP", bbox=[112, 385, 274, 426], confidence=0.99, block_type="cell", table_id="t1", row=3, col=1),
                    IntelligentOcrBlock(page=1, text="8.6", bbox=[274, 345, 422, 385], confidence=0.99, block_type="cell", table_id="t1", row=2, col=2),
                    IntelligentOcrBlock(page=1, text="3.2", bbox=[274, 385, 422, 426], confidence=0.99, block_type="cell", table_id="t1", row=3, col=2),
                    IntelligentOcrBlock(page=1, text="10^9/L", bbox=[422, 345, 583, 385], confidence=0.99, block_type="cell", table_id="t1", row=2, col=3),
                    IntelligentOcrBlock(page=1, text="mg/L", bbox=[422, 385, 583, 426], confidence=0.99, block_type="cell", table_id="t1", row=3, col=3),
                    IntelligentOcrBlock(page=1, text="normal", bbox=[583, 345, 744, 385], confidence=0.99, block_type="cell", table_id="t1", row=2, col=4),
                    IntelligentOcrBlock(page=1, text="normal", bbox=[583, 385, 744, 426], confidence=0.99, block_type="cell", table_id="t1", row=3, col=4),
                ],
                metadata={"model_name": "PP-OCRv5", "accelerator": "directml"},
            )
        },
        profile=profile,
    )
    document_blocks = _blocks_from_intelligent_result(result, {}, document_profile=None)

    assert [(block.reading_order, block.text, block.row, block.col) for block in document_blocks] == [
        (1, "WBC", 2, 1),
        (2, "8.6", 2, 2),
        (3, "10^9/L", 2, 3),
        (4, "normal", 2, 4),
        (5, "CRP", 3, 1),
        (6, "3.2", 3, 2),
        (7, "mg/L", 3, 3),
        (8, "normal", 3, 4),
    ]


def test_real_hardware_manifest_template_documents_required_truth_annotations():
    template = read_config_artifact("ocr_evaluation_profiles", "real_hardware_case_template")

    parsed = template["parsed"]
    assert parsed["profile_id"] == "real_hardware_case_template"
    assert parsed["thresholds"]["template"] is True
    assert parsed["thresholds"]["requires_real_hardware"] is True
    assert parsed["thresholds"]["target_accelerators"] == ["directml", "cuda", "rocm_remote"]
    assert parsed["cases"][0]["tags"] == ["directml", "cuda", "rocm_remote", "table", "paragraph"]
    assert parsed["cases"][0]["truth_blocks"][0]["bbox"] == [120, 90, 860, 128]
    assert parsed["cases"][0]["truth_tables"][0]["cells"][0]["row_span"] == 1
    assert parsed["cases"][0]["truth_tables"][0]["cells"][0]["col_span"] == 1


def test_real_hardware_manifest_template_reports_template_blocker_when_run():
    result = run_ocr_evaluation_profile("real_hardware_case_template")

    assert result["summary"]["quality_band"] == "blocked"
    assert result["summary"]["hard_blocker"] == "template_profile"
    assert result["summary"]["template"] is True
    assert result["cases"] == []


def test_ocr_evaluation_profile_loads_mock_fixture_profile():
    profile = load_ocr_evaluation_profile("mock_general")

    assert profile.profile_id == "mock_general"
    assert profile.default_document_profile == "medical_inpatient_zh"
    assert profile.default_ocr_profile == "cpu_stable"
    assert len(profile.cases) == 1
    assert profile.cases[0].document_path == "fixtures/mock_general_clean_note.txt"
    assert profile.cases[0].truth_pages[1].startswith("基本信息")


def test_ocr_evaluation_profile_loads_synthetic_directml_fixture_profile():
    profile = load_ocr_evaluation_profile("synthetic_medical_directml")

    assert profile.profile_id == "synthetic_medical_directml"
    assert profile.default_document_profile == "medical_inpatient_zh"
    assert profile.default_ocr_profile == "windows_radeon_balanced"
    assert profile.thresholds["synthetic_fixture"] is True
    assert profile.thresholds["requires_real_hardware"] is False
    assert profile.thresholds["requires_deidentified_corpus"] is False
    assert profile.thresholds["target_accelerators"] == ["directml"]
    assert len(profile.cases) == 1
    case = profile.cases[0]
    assert case.document_path == "fixtures/synthetic_medical_directml.png"
    assert case.ocr_profile == "windows_radeon_balanced"
    assert "synthetic" in case.tags
    assert "directml" in case.tags
    assert "table" in case.tags
    assert case.truth_pages[1].startswith("EYEX SYNTHETIC OCR EVAL")
    assert case.truth_blocks[0] == {
        "page": 1,
        "reading_order": 1,
        "text": "EYEX SYNTHETIC OCR EVAL",
        "bbox": [120, 78, 598, 103],
    }
    assert case.truth_blocks[4] == {
        "page": 1,
        "reading_order": 5,
        "text": "Test",
        "bbox": [120, 313, 280, 353],
        "row": 1,
        "col": 1,
    }
    assert case.truth_blocks[9] == {
        "page": 1,
        "reading_order": 10,
        "text": "8.6",
        "bbox": [280, 353, 430, 393],
        "row": 2,
        "col": 2,
    }
    assert case.truth_tables[0]["cells"][0] == {
        "row": 1,
        "col": 1,
        "row_span": 1,
        "col_span": 1,
        "text": "Test",
        "bbox": [120, 313, 280, 353],
    }


def test_read_config_artifact_supports_ocr_evaluation_profiles():
    artifact = read_config_artifact("ocr_evaluation_profiles", "mock_general")

    assert artifact["kind"] == "ocr_evaluation_profiles"
    assert artifact["config_id"] == "mock_general"
    assert artifact["parsed"]["profile_id"] == "mock_general"


def test_run_ocr_evaluation_profile_returns_weighted_summary():
    result = run_ocr_evaluation_profile("mock_general")

    assert result["profile"]["profile_id"] == "mock_general"
    assert result["environment"]["selected_profile"] == "mock_general"
    assert result["environment"]["target_accelerators"] == []
    assert "accelerator_probe" in result["environment"]
    assert "run_commands" in result["environment"]
    assert result["summary"]["total_cases"] == 1
    assert result["summary"]["passed_cases"] == 1
    assert result["summary"]["avg_cer"] == 0.0
    assert result["summary"]["avg_wer"] == 0.0
    assert result["summary"]["quality_band"] == "excellent"
    assert result["cases"][0]["case_id"] == "mock-general-clean-note"
    assert result["cases"][0]["ocr_engine"] == "plain_text"
    assert result["cases"][0]["cer"] == 0.0
    assert result["cases"][0]["wer"] == 0.0
    assert result["cases"][0]["ocr_profile"] == "cpu_stable"
    assert result["cases"][0]["document_profile"] == "medical_inpatient_zh"
    assert result["cases"][0]["layout_metrics"]["truth_block_count"] == 0
    assert result["cases"][0]["table_metrics"]["truth_table_cell_count"] == 0
    assert result["summary"]["avg_block_text_match_accuracy"] is None
    assert result["summary"]["avg_table_cell_text_accuracy"] is None
    assert result["cases"][0]["page_results"][0]["quality_band"] == "excellent"


def test_run_ocr_evaluation_profile_blocks_stale_configured_sidecar_before_cases(monkeypatch):
    monkeypatch.setattr(settings, "ocr_document_ai_url", "http://127.0.0.1:8765/extract")

    def fake_get_json(url: str, timeout: float) -> dict:
        return {
            "ok": True,
            "api_contract_version": "eyex-ocr-sidecar-v2",
            "ocr_profile": {
                "profile_id": "windows_radeon_balanced",
                "merge_policy_version": "ocr-canonical-layout-v2",
            },
            "device": {"resolved": "directml", "accelerator": "directml", "available_accelerators": ["directml"]},
            "strong_pipeline_readiness": {"ready": True, "stages": {}},
        }

    result = run_ocr_evaluation_profile("synthetic_medical_directml", http_get_json=fake_get_json)

    assert result["summary"]["hard_blocker"] == "stale_ocr_sidecar"
    assert result["summary"]["quality_band"] == "blocked"
    assert result["cases"] == []
    assert "ocr-canonical-layout-v3" in result["summary"]["blocker_message"]
    assert result["environment"]["sidecar_preflight"]["ready"] is False
    assert any(action["command"] == ".\\stop.cmd" for action in result["environment"]["sidecar_preflight"]["actions"])


def test_run_ocr_evaluation_profile_blocks_unverified_configured_sidecar_before_cases(monkeypatch):
    monkeypatch.setattr(settings, "ocr_document_ai_url", "http://127.0.0.1:8765/extract")

    def fake_get_json(url: str, timeout: float) -> dict:
        raise RuntimeError("connection refused")

    result = run_ocr_evaluation_profile("synthetic_medical_directml", http_get_json=fake_get_json)

    assert result["summary"]["hard_blocker"] == "ocr_sidecar_preflight_failed"
    assert result["summary"]["quality_band"] == "blocked"
    assert result["cases"] == []
    assert "OCR sidecar" in result["summary"]["blocker_message"]
    assert result["environment"]["sidecar_preflight"]["ready"] is False
    assert any(action["command"] == ".\\start.cmd" for action in result["environment"]["sidecar_preflight"]["actions"])


def test_project_config_accepts_ocr_evaluation_profiles():
    assert validate_project_config() == []


def test_ocr_evaluation_rejects_incomplete_real_hardware_annotations(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    profile_dir = config_dir / "ocr_evaluation_profiles"
    profile_dir.mkdir(parents=True)
    fixture = profile_dir / "case.txt"
    fixture.write_text("姓名：张三", encoding="utf-8")
    (profile_dir / "medical_inpatient_zh.yaml").write_text(
        """
profile_id: medical_inpatient_zh
label: Real corpus contract fixture
thresholds:
  requires_real_hardware: true
  requires_deidentified_corpus: true
  min_cases: 1
cases:
  - case_id: incomplete
    document_path: case.txt
    truth_pages:
      1: "姓名：张三"
""",
        encoding="utf-8",
    )
    monkeypatch.setattr("app.core.config_loader.settings.config_dir", config_dir)

    messages = validate_ocr_evaluation_profiles()

    assert messages == [
        "OCR evaluation case incomplete in medical_inpatient_zh.yaml must define truth_blocks with text, bbox, reading_order, and page",
        "OCR evaluation case incomplete in medical_inpatient_zh.yaml must define truth_tables for table/layout evaluation",
    ]


def test_hardware_ocr_eval_profile_declares_real_gpu_dataset_contract():
    profile = load_ocr_evaluation_profile("medical_inpatient_zh")

    assert profile.default_ocr_profile == "windows_radeon_balanced"
    assert profile.thresholds["requires_real_hardware"] is True
    assert profile.thresholds["requires_deidentified_corpus"] is True
    assert profile.thresholds["min_cases"] >= 5
    assert profile.thresholds["target_accelerators"] == ["directml", "cuda", "rocm_remote"]
    assert profile.cases == []

    result = run_ocr_evaluation_profile("medical_inpatient_zh")

    assert result["summary"]["quality_band"] == "blocked"
    assert result["summary"]["hard_blocker"] == "missing_real_hardware_corpus"
    assert result["environment"]["target_accelerators"] == ["directml", "cuda", "rocm_remote"]
    assert result["environment"]["target_readiness"]["directml"]["profile_id"] == "windows_radeon_balanced"
    assert result["environment"]["target_readiness"]["cuda"]["profile_id"] == "cuda_paddle"
    assert result["environment"]["target_readiness"]["rocm_remote"]["profile_id"] == "rocm_remote_vl"
