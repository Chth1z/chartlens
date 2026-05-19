from __future__ import annotations

import sys
import types
from pathlib import Path

from app.core.config_loader import load_ocr_profile
from app.core.settings import settings
from app.services.ocr_accelerators import accelerator_probe
from app.services.ocr_engine import (
    RapidOcrPageInput,
    IntelligentOcrBlock,
    IntelligentOcrResult,
)
from app.services.ocr_engine.engines import (
    PPOCRV5OnnxDirectMLEngine,
    PPOCRV5PaddleEngine,
)
from app.services.ocr_engine import errors as _ocr_errors
from app.services.ocr_engine.engines import ppocrv5_directml as _directml_mod
from app.services.ocr_engine.engines import ppocrv5_paddle as _paddle_mod


def test_pp_ocr_v5_paddle_engine_uses_official_version_parameter(monkeypatch, tmp_path):
    calls = {}

    class FakePaddleOCR:
        def __init__(self, **kwargs):
            calls["init"] = kwargs

        def predict(self, input):
            calls["input"] = input
            return [{"rec_texts": ["既往史：否认高血压"], "rec_scores": [0.98]}]

    monkeypatch.setattr(_paddle_mod, "paddleocr_package_available", lambda: True)
    monkeypatch.setattr(_paddle_mod, "import_paddle_ocr_class", lambda: FakePaddleOCR)
    monkeypatch.setattr(_paddle_mod, "preload_torch_for_windows", lambda: None)
    file_path = tmp_path / "case.png"
    file_path.write_bytes(b"image")

    result = PPOCRV5PaddleEngine().extract(file_path)

    assert calls["init"]["ocr_version"] == "PP-OCRv5"
    assert calls["init"]["lang"] == "ch"
    assert calls["input"] == str(file_path)
    assert result.blocks[0].text == "既往史：否认高血压"
    assert result.metadata["model_name"] == "PP-OCRv5"


def test_directml_engine_reports_missing_model_dir_before_provider(monkeypatch):
    monkeypatch.setattr(settings, "ocr_directml_model_dir", None)

    engine = PPOCRV5OnnxDirectMLEngine()

    assert engine.available() is False
    assert "EYEX_OCR_DIRECTML_MODEL_DIR" in engine.unavailable_reason()


def test_directml_engine_reports_missing_provider(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "ocr_directml_model_dir", tmp_path)
    monkeypatch.setattr(_directml_mod, "_onnx_available_providers", lambda: ["CPUExecutionProvider"])
    (tmp_path / "ch_PP-OCRv5_det_server.onnx").write_bytes(b"det")
    (tmp_path / "ch_PP-OCRv5_rec_server.onnx").write_bytes(b"rec")

    engine = PPOCRV5OnnxDirectMLEngine()

    assert engine.available() is False
    assert "DmlExecutionProvider" in engine.unavailable_reason()


def test_directml_engine_enables_dml_for_detection_classification_and_recognition(monkeypatch, tmp_path):
    calls = {}

    class FakeOCRVersion:
        PPOCRV5 = "PP-OCRv5"

    class FakeModelType:
        SERVER = "server"

    class FakeRapidOCR:
        def __init__(self, *, params):
            calls["params"] = params

        def __call__(self, image_path):
            calls["image_path"] = image_path
            return types.SimpleNamespace(
                boxes=[[[0, 0], [10, 0], [10, 10], [0, 10]]],
                txts=("高血压",),
                scores=(0.97,),
            )

    fake_module = types.SimpleNamespace(RapidOCR=FakeRapidOCR, OCRVersion=FakeOCRVersion, ModelType=FakeModelType)
    monkeypatch.setitem(sys.modules, "rapidocr", fake_module)
    monkeypatch.setattr(_directml_mod.importlib.util, "find_spec", lambda name: object() if name == "rapidocr" else None)
    monkeypatch.setattr(_directml_mod, "_onnx_available_providers", lambda: ["DmlExecutionProvider", "CPUExecutionProvider"])
    monkeypatch.setattr(
        _directml_mod,
        "ocr_engine_options",
        lambda engine_id: {
            "model_type": "server",
            "render_dpi": 400,
            "rapidocr_max_side_len": 2048,
            "image_preprocess": "none",
            "directml_safe_mode": True,
            "tile_max_side_len": 2048,
            "tile_overlap": 256,
        },
    )
    monkeypatch.setattr(settings, "ocr_directml_model_dir", tmp_path)
    (tmp_path / "ch_PP-OCRv5_det_server.onnx").write_bytes(b"det")
    (tmp_path / "ch_PP-OCRv5_rec_server.onnx").write_bytes(b"rec")
    file_path = tmp_path / "page.png"
    from PIL import Image

    Image.new("RGB", (64, 32), color="white").save(file_path)

    result = PPOCRV5OnnxDirectMLEngine().extract(file_path)

    assert calls["params"]["Global.model_root_dir"] == str(tmp_path)
    assert calls["params"]["EngineConfig.onnxruntime.use_dml"] is True
    assert calls["params"]["Det.ocr_version"] == "PP-OCRv5"
    assert calls["params"]["Rec.ocr_version"] == "PP-OCRv5"
    assert calls["params"]["Det.model_type"] == "server"
    assert calls["params"]["Rec.model_type"] == "server"
    assert calls["params"]["Global.max_side_len"] == 2048
    assert result.metadata["accelerator"] == "directml"
    assert result.metadata["model_variant"] == "server"
    assert result.metadata["render_dpi"] == 400
    assert result.metadata["directml_safe_mode"] is True
    assert result.metadata["tile_max_side_len"] == 2048
    assert result.metadata["tile_overlap"] == 256


def test_directml_parser_accepts_numpy_backed_rapidocr_outputs():
    import numpy as np

    from app.services.ocr_engine.payload_parse import blocks_from_rapidocr_output

    output = types.SimpleNamespace(
        boxes=np.array([[[1, 2], [21, 2], [21, 12], [1, 12]]], dtype=np.float32),
        txts=("白细胞",),
        scores=np.array([0.97], dtype=np.float32),
    )

    blocks = blocks_from_rapidocr_output(output, page=3)

    assert len(blocks) == 1
    assert blocks[0].page == 3
    assert blocks[0].text == "白细胞"
    assert blocks[0].bbox == [1.0, 2.0, 21.0, 12.0]
    assert blocks[0].confidence == 0.9700000286102295


def test_payload_parser_does_not_turn_candidate_metadata_into_ocr_blocks():
    from app.services.ocr_engine.payload_parse import result_from_payload

    result = result_from_payload(
        "paddleocr_hybrid",
        {
            "blocks": [
                {
                    "text": "白细胞",
                    "bbox": [1, 2, 21, 12],
                    "confidence": 0.97,
                    "candidate_id": "pp_ocr_v5:0001:abcd",
                    "merge_flags": ["canonical_selected"],
                    "canonical_source_ids": ["pp_structure_v3:0001"],
                    "layout_region_id": "layout:p1:0001",
                    "line_group_id": "line:p1:0001",
                }
            ],
            "metadata": {
                "raw_candidates": {
                    "pp_ocr_v5": [
                        {"text": "白细胞", "candidate_id": "pp_ocr_v5:0001:abcd"}
                    ]
                },
                "stage_metrics": {"pp_ocr_v5": {"status": "completed"}},
            },
        },
        default_confidence=0.8,
    )

    assert [block.text for block in result.blocks] == ["白细胞"]


def test_directml_runtime_failure_disables_gpu_until_sidecar_restart(monkeypatch, tmp_path):
    class FakeOCRVersion:
        PPOCRV5 = "PP-OCRv5"

    class FakeModelType:
        SERVER = "server"

    class FakeRapidOCR:
        def __init__(self, *, params):
            pass

        def __call__(self, image_path):
            raise RuntimeError("DXGI_ERROR_DEVICE_REMOVED")

    fake_module = types.SimpleNamespace(RapidOCR=FakeRapidOCR, OCRVersion=FakeOCRVersion, ModelType=FakeModelType)
    _ocr_errors.reset_directml_state()
    monkeypatch.setitem(sys.modules, "rapidocr", fake_module)
    monkeypatch.setattr(_directml_mod.importlib.util, "find_spec", lambda name: object() if name == "rapidocr" else None)
    monkeypatch.setattr(_directml_mod, "_onnx_available_providers", lambda: ["DmlExecutionProvider", "CPUExecutionProvider"])
    monkeypatch.setattr(
        _directml_mod,
        "ocr_engine_options",
        lambda engine_id: {
            "model_type": "server",
            "render_dpi": 400,
            "rapidocr_max_side_len": 2048,
            "image_preprocess": "none",
            "directml_safe_mode": True,
            "tile_max_side_len": 2048,
            "tile_overlap": 256,
        },
    )
    monkeypatch.setattr(settings, "ocr_directml_model_dir", tmp_path)
    (tmp_path / "ch_PP-OCRv5_det_server.onnx").write_bytes(b"det")
    (tmp_path / "ch_PP-OCRv5_rec_server.onnx").write_bytes(b"rec")
    file_path = tmp_path / "page.png"
    from PIL import Image

    Image.new("RGB", (64, 32), color="white").save(file_path)

    engine = PPOCRV5OnnxDirectMLEngine()
    try:
        engine.extract(file_path)
    except RuntimeError as exc:
        assert "DXGI_ERROR_DEVICE_REMOVED" in str(exc)
    else:
        raise AssertionError("DirectML runtime failure was not raised")

    assert engine.available() is False
    assert "DirectML disabled for this OCR sidecar process" in engine.unavailable_reason()


def test_directml_accelerator_probe_reports_process_runtime_disable(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "ocr_directml_model_dir", tmp_path)
    monkeypatch.setattr(_ocr_errors, "_DIRECTML_RUNTIME_DISABLED_REASON", "driver timeout")
    monkeypatch.setattr(_directml_mod, "_onnx_available_providers", lambda: ["DmlExecutionProvider", "CPUExecutionProvider"])
    (tmp_path / "ch_PP-OCRv5_det_server.onnx").write_bytes(b"det")
    (tmp_path / "ch_PP-OCRv5_rec_server.onnx").write_bytes(b"rec")

    probe = accelerator_probe()["directml"]

    assert probe["available"] is False
    assert probe["runtime_disabled"] is True
    assert probe["runtime_disabled_reason"] == "driver timeout"


def test_directml_engine_selects_best_render_dpi_candidate(monkeypatch, tmp_path):
    _ocr_errors.reset_directml_state()
    calls = []

    class FakeOCRVersion:
        PPOCRV5 = "PP-OCRv5"

    class FakeModelType:
        SERVER = "server"

    class FakeRapidOCR:
        def __init__(self, *, params):
            pass

        def __call__(self, image_path):
            calls.append(str(image_path))
            if "dpi400" in str(image_path):
                return types.SimpleNamespace(
                    boxes=[
                        [[0, 0], [20, 0], [20, 10], [0, 10]],
                        [[0, 12], [40, 12], [40, 22], [0, 22]],
                    ],
                    txts=("短文本", "更长的候选文本"),
                    scores=(0.90, 0.91),
                )
            return types.SimpleNamespace(
                boxes=[[[0, 0], [20, 0], [20, 10], [0, 10]]],
                txts=("短文本",),
                scores=(0.99,),
            )

    fake_module = types.SimpleNamespace(RapidOCR=FakeRapidOCR, OCRVersion=FakeOCRVersion, ModelType=FakeModelType)
    monkeypatch.setitem(sys.modules, "rapidocr", fake_module)
    monkeypatch.setattr(_directml_mod.importlib.util, "find_spec", lambda name: object() if name == "rapidocr" else None)
    monkeypatch.setattr(_directml_mod, "_onnx_available_providers", lambda: ["DmlExecutionProvider", "CPUExecutionProvider"])
    monkeypatch.setattr(
        _directml_mod,
        "ocr_engine_options",
        lambda engine_id: {
            "model_type": "server",
            "render_dpi": 300,
            "render_dpi_candidates": [300, 400],
            "rapidocr_max_side_len": 1536,
            "image_preprocess": "none",
            "directml_safe_mode": True,
            "tile_max_side_len": 1536,
            "tile_overlap": 192,
            "page_render_workers": 3,
        },
    )
    monkeypatch.setattr(settings, "ocr_directml_model_dir", tmp_path)
    (tmp_path / "ch_PP-OCRv5_det_server.onnx").write_bytes(b"det")
    (tmp_path / "ch_PP-OCRv5_rec_server.onnx").write_bytes(b"rec")

    def fake_page_inputs(file_path, *, render_scale, preprocess_mode, directml_safe_mode, tile_max_side_len, tile_overlap, page_render_workers):
        dpi = round(render_scale * 72)
        assert page_render_workers == 3
        return [RapidOcrPageInput(page=1, image_path=tmp_path / f"dpi{dpi}.png")]

    monkeypatch.setattr(_directml_mod, "iter_rapidocr_page_inputs", fake_page_inputs)

    result = PPOCRV5OnnxDirectMLEngine().extract(tmp_path / "case.pdf")

    assert [Path(call).stem for call in calls] == ["dpi300", "dpi400"]
    assert result.metadata["render_dpi"] == 400
    assert result.metadata["render_dpi_candidates"] == [300, 400]
    assert result.metadata["ocr_candidate_metrics"] == [
        {
            "render_dpi": 300,
            "preprocess_modes": ["none"],
            "block_count": 1,
            "char_count": 3,
            "avg_confidence": 0.99,
            "tile_count": 1,
            "selected": False,
        },
        {
            "render_dpi": 400,
            "preprocess_modes": ["none"],
            "block_count": 2,
            "char_count": 10,
            "avg_confidence": 0.905,
            "tile_count": 1,
            "selected": True,
        },
    ]
    assert [block.text for block in result.blocks] == ["短文本", "更长的候选文本"]


def test_directml_engine_runs_pdf_pages_through_rendered_images(monkeypatch, tmp_path):
    _ocr_errors.reset_directml_state()
    calls = []
    page_input_kwargs = []

    class FakeOCRVersion:
        PPOCRV5 = "PP-OCRv5"

    class FakeModelType:
        SERVER = "server"

    class FakeRapidOCR:
        def __init__(self, *, params):
            assert params["EngineConfig.onnxruntime.use_dml"] is True

        def __call__(self, image_path):
            calls.append(str(image_path))
            return types.SimpleNamespace(
                boxes=[[[0, 0], [20, 0], [20, 10], [0, 10]]],
                txts=(Path(image_path).stem,),
                scores=(0.98,),
            )

    fake_module = types.SimpleNamespace(RapidOCR=FakeRapidOCR, OCRVersion=FakeOCRVersion, ModelType=FakeModelType)
    monkeypatch.setitem(sys.modules, "rapidocr", fake_module)
    monkeypatch.setattr(_directml_mod.importlib.util, "find_spec", lambda name: object() if name == "rapidocr" else None)
    monkeypatch.setattr(_directml_mod, "_onnx_available_providers", lambda: ["DmlExecutionProvider", "CPUExecutionProvider"])
    monkeypatch.setattr(
        _directml_mod,
        "ocr_engine_options",
        lambda engine_id: {
            "model_type": "server",
            "render_dpi": 400,
            "rapidocr_max_side_len": 2048,
            "image_preprocess_modes": ["none", "grayscale_autocontrast_sharpen"],
            "directml_safe_mode": True,
            "tile_max_side_len": 2048,
            "tile_overlap": 256,
            "page_render_workers": 2,
        },
    )
    monkeypatch.setattr(settings, "ocr_directml_model_dir", tmp_path)
    (tmp_path / "ch_PP-OCRv5_det_server.onnx").write_bytes(b"det")
    (tmp_path / "ch_PP-OCRv5_rec_server.onnx").write_bytes(b"rec")
    page_1 = tmp_path / "page-1.png"
    page_2 = tmp_path / "page-2.png"

    def fake_page_inputs(file_path, *, render_scale, preprocess_mode, directml_safe_mode, tile_max_side_len, tile_overlap, page_render_workers):
        page_input_kwargs.append(
            {
                "render_scale": render_scale,
                "preprocess_mode": preprocess_mode,
                "directml_safe_mode": directml_safe_mode,
                "tile_max_side_len": tile_max_side_len,
                "tile_overlap": tile_overlap,
                "page_render_workers": page_render_workers,
            }
        )
        return [
            RapidOcrPageInput(page=1, image_path=page_1, offset_x=10, offset_y=20),
            RapidOcrPageInput(page=2, image_path=page_2, offset_x=0, offset_y=0),
        ]

    monkeypatch.setattr(_directml_mod, "iter_rapidocr_page_inputs", fake_page_inputs)
    file_path = tmp_path / "case.pdf"
    file_path.write_bytes(b"%PDF fixture")

    result = PPOCRV5OnnxDirectMLEngine().extract(file_path)

    assert calls == [str(page_1), str(page_2), str(page_1), str(page_2)]
    assert page_input_kwargs == [
        {
            "render_scale": 400 / 72.0,
            "preprocess_mode": "none",
            "directml_safe_mode": True,
            "tile_max_side_len": 2048,
            "tile_overlap": 256,
            "page_render_workers": 2,
        },
        {
            "render_scale": 400 / 72.0,
            "preprocess_mode": "grayscale_autocontrast_sharpen",
            "directml_safe_mode": True,
            "tile_max_side_len": 2048,
            "tile_overlap": 256,
            "page_render_workers": 2,
        },
    ]
    assert [block.page for block in result.blocks] == [1, 2]
    assert [block.text for block in result.blocks] == ["page-1", "page-2"]
    assert result.blocks[0].bbox == [10.0, 20.0, 30.0, 30.0]
    assert result.metadata["image_preprocess_modes"] == ["none", "grayscale_autocontrast_sharpen"]
    assert result.metadata["page_render_workers"] == 2
