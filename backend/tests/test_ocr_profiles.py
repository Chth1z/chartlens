from __future__ import annotations

import sys
import types
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config_loader import load_ocr_profile, list_ocr_profiles
from app.core.settings import settings
from app.domain.models import DocumentIRBlock, OcrDeviceStatus
from app.main import app
from app.services import ocr
from app.services.ocr_accelerators import accelerator_probe
from app.services.ocr_engine import (
    RapidOcrPageInput,
    IntelligentOcrBlock,
    IntelligentOcrResult,
    default_intelligent_ocr_engines,
)
from app.services.ocr_engine.canonicalize import _hybrid_required_model_stages, _merge_hybrid_ocr_results
from app.services.ocr_engine.engines import (
    PPOCRV5OnnxDirectMLEngine,
    PPOCRV5PaddleEngine,
    PaddleOcrHybridPipelineEngine,
    RemotePaddleOCRVLEngine,
)
from app.services.ocr_engine.postprocessing import dedupe_ocr_blocks as _dedupe_ocr_blocks
from app.services.ocr_engine import engine_base as _engine_base
from app.services.ocr_engine import errors as _ocr_errors
from app.services.ocr_engine.engines import ppocrv5_directml as _directml_mod
from app.services.ocr_engine.engines import ppocrv5_paddle as _paddle_mod
from app.services.ocr_engine.engines import hybrid_pipeline as _hybrid_mod
from ocr_sidecar import main as sidecar_main


def test_ocr_profiles_load_default_and_named_profiles():
    default_profile = load_ocr_profile("windows_radeon_balanced")
    profile_ids = {profile.profile_id for profile in list_ocr_profiles()}

    assert default_profile.profile_id == "windows_radeon_balanced"
    assert default_profile.pipeline_stages == ["preprocess", "pp_structure_v3", "pp_ocr_v5", "merge"]
    assert default_profile.render_dpi == 300
    assert default_profile.preprocess_profile == "document_multi_dpi"
    assert default_profile.merge_policy_version == "ocr-canonical-layout-v3"
    assert [engine.engine_id for engine in default_profile.engines] == ["paddleocr_hybrid"]
    assert "cpu_stable" in profile_ids
    assert "cuda_paddle" in profile_ids
    assert "rocm_remote_vl" in profile_ids


def test_default_engine_order_comes_from_ocr_profile(monkeypatch):
    monkeypatch.setattr(settings, "ocr_profile", "windows_radeon_balanced")
    monkeypatch.setattr(settings, "ocr_document_ai_url", None)
    monkeypatch.setattr(_engine_base, "load_ocr_profile", lambda profile_id=None: load_ocr_profile("windows_radeon_balanced"))

    names = [engine.name for engine in default_intelligent_ocr_engines(page_kind="image_ocr")]

    assert names == ["paddleocr_hybrid"]


def test_windows_radeon_profile_uses_directml_guarded_pipeline_without_local_cpu_heavy_stages():
    profile = load_ocr_profile("windows_radeon_balanced")
    routed = {
        page_kind: rule.engines
        for rule in profile.page_router
        for page_kind in rule.page_kinds
        if page_kind not in {"native_pdf_text", "text"}
    }
    hybrid_engine = profile.engine_config("paddleocr_hybrid")
    pp_ocr_stage = profile.stage_models["pp_ocr_v5"]

    assert routed["image_ocr"] == ["paddleocr_hybrid"]
    assert routed["table"] == ["paddleocr_hybrid"]
    assert routed["low_quality"] == ["paddleocr_hybrid"]
    assert _hybrid_required_model_stages(profile) == ["pp_structure_v3", "pp_ocr_v5"]
    assert hybrid_engine is not None
    assert hybrid_engine.options["pipeline"] == "canonical_layout_v3"
    assert "paddleocr_vl" not in profile.stage_models
    assert profile.stage_models["pp_structure_v3"]["enabled"] is True
    assert profile.stage_models["pp_structure_v3"]["required"] is True
    assert profile.stage_models["pp_structure_v3"]["role"] == "layout_table_reading_order_parser"
    assert pp_ocr_stage["engine_id"] == "pp_ocr_v5_onnx_directml"
    assert pp_ocr_stage["fallback_engine_ids"] == []
    assert pp_ocr_stage["options"]["model_type"] == "server"
    assert pp_ocr_stage["options"]["render_dpi"] == 300
    assert pp_ocr_stage["options"]["render_dpi_candidates"] == [300, 400, 500, 600]
    assert pp_ocr_stage["options"]["directml_safe_mode"] is True
    assert pp_ocr_stage["options"]["rapidocr_max_side_len"] <= 2048
    assert pp_ocr_stage["options"]["tile_max_side_len"] == 1536
    assert pp_ocr_stage["options"]["tile_overlap"] >= 192
    assert pp_ocr_stage["options"]["image_preprocess"] == "none"


def test_nvidia_cuda_profile_uses_canonical_hybrid_pipeline():
    profile = load_ocr_profile("cuda_paddle")
    routed = {
        page_kind: rule.engines
        for rule in profile.page_router
        for page_kind in rule.page_kinds
        if page_kind not in {"native_pdf_text", "text"}
    }
    hybrid_engine = profile.engine_config("paddleocr_hybrid")

    assert routed["image_ocr"] == ["paddleocr_hybrid"]
    assert routed["table"] == ["paddleocr_hybrid"]
    assert routed["low_quality"] == ["paddleocr_hybrid"]
    assert profile.pipeline_stages == ["preprocess", "pp_structure_v3", "pp_ocr_v5", "merge"]
    assert profile.merge_policy_version == "ocr-canonical-layout-v3"
    assert [engine.engine_id for engine in profile.engines] == ["paddleocr_hybrid"]
    assert hybrid_engine is not None
    assert hybrid_engine.accelerator == "cuda"
    assert hybrid_engine.options["pipeline"] == "canonical_layout_v3"
    assert _hybrid_required_model_stages(profile) == ["pp_structure_v3", "pp_ocr_v5"]
    assert profile.stage_models["pp_structure_v3"]["engine_id"] == "paddle_structure_v3"
    assert profile.stage_models["pp_structure_v3"]["accelerator"] == "cuda"
    assert profile.stage_models["pp_ocr_v5"]["engine_id"] == "pp_ocr_v5_paddle"
    assert profile.stage_models["pp_ocr_v5"]["accelerator"] == "cuda"


def test_rocm_remote_profile_is_remote_vl_only_without_cpu_heavy_fallbacks():
    profile = load_ocr_profile("rocm_remote_vl")
    routed = {
        page_kind: rule.engines
        for rule in profile.page_router
        for page_kind in rule.page_kinds
        if page_kind not in {"native_pdf_text", "text"}
    }

    assert routed["image_ocr"] == ["paddleocr_vl_remote"]
    assert [engine.engine_id for engine in profile.engines] == ["paddleocr_vl_remote"]
    assert profile.gpu_policy["rocm_default_enabled"] is True


def test_directml_guarded_hybrid_engine_requires_layout_stages_for_strong_ocr():
    profile = load_ocr_profile("windows_radeon_balanced")

    class FakeDirectMLEngine:
        name = "pp_ocr_v5_onnx_directml"

        def available(self) -> bool:
            return True

        def extract(self, file_path: Path) -> IntelligentOcrResult:
            return IntelligentOcrResult(
                engine=self.name,
                blocks=[IntelligentOcrBlock(page=1, text="主诉：腹痛", bbox=[0, 0, 80, 20], confidence=0.98)],
                metadata={"model_name": "PP-OCRv5", "accelerator": "directml"},
            )

    engine = PaddleOcrHybridPipelineEngine(stage_registry={"pp_ocr_v5_onnx_directml": FakeDirectMLEngine()})

    assert "pp_structure_v3" in engine.unavailable_reason()


def test_hybrid_pipeline_degrades_when_structure_stage_times_out(monkeypatch):
    base_profile = load_ocr_profile("windows_radeon_balanced")
    profile = base_profile.model_copy(
        update={
            "engines": [
                base_profile.engine_config("paddleocr_hybrid").model_copy(
                    update={"options": {"pipeline": "canonical_layout_v3", "timeout_seconds": 2}}
                )
            ],
            "stage_models": {
                **base_profile.stage_models,
                "pp_structure_v3": {
                    **base_profile.stage_models["pp_structure_v3"],
                    "timeout_seconds": 0.01,
                },
                "pp_ocr_v5": {
                    **base_profile.stage_models["pp_ocr_v5"],
                    "timeout_seconds": 1,
                },
            },
        }
    )

    class SlowStructureEngine:
        name = "paddle_structure_v3"

        def available(self) -> bool:
            return True

        def extract(self, file_path: Path) -> IntelligentOcrResult:
            import time

            time.sleep(0.05)
            return IntelligentOcrResult(engine=self.name, blocks=[])

    class DirectMlTextEngine:
        name = "pp_ocr_v5_onnx_directml"

        def available(self) -> bool:
            return True

        def extract(self, file_path: Path) -> IntelligentOcrResult:
            return IntelligentOcrResult(
                engine=self.name,
                blocks=[IntelligentOcrBlock(page=1, text="主诉：腹痛", bbox=[0, 0, 80, 20], confidence=0.98)],
                metadata={"model_name": "PP-OCRv5", "accelerator": "directml"},
            )

    monkeypatch.setattr(_hybrid_mod, "active_ocr_profile", lambda: profile)

    engine = PaddleOcrHybridPipelineEngine(
        stage_registry={
            "paddle_structure_v3": SlowStructureEngine(),
            "pp_ocr_v5_onnx_directml": DirectMlTextEngine(),
        }
    )

    result = engine.extract(Path("case.pdf"))

    assert [block.text for block in result.blocks] == ["主诉：腹痛"]
    assert result.metadata["stage_metrics"]["pp_ocr_v5"]["status"] == "completed"
    assert result.metadata["stage_metrics"]["pp_structure_v3"]["status"] == "failed"
    assert "PAGE_TIMEOUT" in result.metadata["stage_errors"]["pp_structure_v3"]


def test_remote_vl_uses_dedicated_rocm_url_not_local_document_ai_url(monkeypatch):
    monkeypatch.setattr(settings, "ocr_document_ai_url", "http://127.0.0.1:8765/extract")
    monkeypatch.setattr(settings, "ocr_paddleocr_vl_url", None)

    missing = RemotePaddleOCRVLEngine()

    assert missing.available() is False
    assert "EYEX_OCR_PADDLEOCR_VL_URL" in missing.unavailable_reason()

    monkeypatch.setattr(settings, "ocr_paddleocr_vl_url", "http://10.0.0.8:8765/extract")

    configured = RemotePaddleOCRVLEngine()

    assert configured.available() is True
    assert configured.endpoint == "http://10.0.0.8:8765/extract"


def test_remote_accelerator_probe_reports_dedicated_vl_url(monkeypatch):
    monkeypatch.setattr(settings, "ocr_document_ai_url", "http://127.0.0.1:8765/extract")
    monkeypatch.setattr(settings, "ocr_paddleocr_vl_url", None)

    missing = accelerator_probe()["remote"]

    assert missing["available"] is False
    assert missing["url"] == ""

    monkeypatch.setattr(settings, "ocr_paddleocr_vl_url", "http://10.0.0.8:8765/extract")

    configured = accelerator_probe()["remote"]

    assert configured["available"] is True
    assert configured["url"] == "http://10.0.0.8:8765/extract"


def test_document_ai_sidecar_is_preferred_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "ocr_profile", "windows_radeon_balanced")
    monkeypatch.setattr(settings, "ocr_document_ai_url", "http://127.0.0.1:8765/extract")
    monkeypatch.setattr(_engine_base, "load_ocr_profile", lambda profile_id=None: load_ocr_profile("windows_radeon_balanced"))

    names = [engine.name for engine in default_intelligent_ocr_engines(page_kind="image_ocr")]

    assert names == ["document_ai_http"]


def test_stale_engine_order_setting_does_not_override_ocr_profile(monkeypatch):
    monkeypatch.setattr(settings, "ocr_profile", "windows_radeon_balanced")
    monkeypatch.setattr(settings, "ocr_document_ai_url", "http://127.0.0.1:8765/extract")
    monkeypatch.setattr(_engine_base, "load_ocr_profile", lambda profile_id=None: load_ocr_profile("windows_radeon_balanced"))

    names = [engine.name for engine in default_intelligent_ocr_engines(page_kind="image_ocr")]

    assert not hasattr(settings, "ocr_intelligent_engines")
    assert names == ["document_ai_http"]


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


def test_ocr_cache_key_includes_engine_and_accelerator(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_dir", tmp_path)
    monkeypatch.setattr(settings, "ocr_profile", "windows_radeon_balanced")

    cpu_path = ocr._ocr_cache_path(b"same", page=1, engine_id="pp_ocr_v5_paddle", accelerator="cpu")
    directml_path = ocr._ocr_cache_path(b"same", page=1, engine_id="pp_ocr_v5_onnx_directml", accelerator="directml")

    assert cpu_path != directml_path


def test_ocr_cache_key_includes_dpi_preprocess_stage_and_merge_policy(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_dir", tmp_path)
    monkeypatch.setattr(settings, "ocr_profile", "windows_radeon_balanced")

    base = ocr._ocr_cache_path(
        b"same",
        page=1,
        engine_id="paddleocr_hybrid",
        render_dpi=300,
        preprocess_profile="document_orientation_unwarp",
        stage="paddleocr_vl",
        model_name="PaddleOCR-VL-1.5",
        model_version="1.5",
        merge_policy_version="ocr-canonical-layout-v3",
        ocr_profile_version="3.1.0",
        ocr_options_fingerprint="tile=1536",
    )
    changed_dpi = ocr._ocr_cache_path(
        b"same",
        page=1,
        engine_id="paddleocr_hybrid",
        render_dpi=400,
        preprocess_profile="document_orientation_unwarp",
        stage="paddleocr_vl",
        model_name="PaddleOCR-VL-1.5",
        model_version="1.5",
        merge_policy_version="ocr-canonical-layout-v3",
        ocr_profile_version="3.1.0",
        ocr_options_fingerprint="tile=1536",
    )
    changed_tile = ocr._ocr_cache_path(
        b"same",
        page=1,
        engine_id="paddleocr_hybrid",
        render_dpi=300,
        preprocess_profile="document_orientation_unwarp",
        stage="paddleocr_vl",
        model_name="PaddleOCR-VL-1.5",
        model_version="1.5",
        merge_policy_version="ocr-canonical-layout-v3",
        ocr_profile_version="3.1.0",
        ocr_options_fingerprint="tile=2048",
    )

    assert base != changed_dpi
    assert base != changed_tile


def test_ocr_cache_fingerprint_includes_canonical_layout_version():
    assert "ocr-canonical-layout-v3" in ocr._ocr_extractor_cache_fingerprint()


def test_rapidocr_tile_fragments_stitch_into_complete_lines():
    blocks = [
        IntelligentOcrBlock(
            page=1,
            text="现病史：患者于1年前无明显诱因开始出现左下腹痛，呈",
            bbox=[706, 907, 1535, 945],
            confidence=0.99,
        ),
        IntelligentOcrBlock(
            page=1,
            text="1年前无明显诱因开始出现左下腹痛，呈胀痛，尚可忍受，",
            bbox=[949, 906, 1800, 948],
            confidence=0.98,
        ),
        IntelligentOcrBlock(
            page=1,
            text="既往史：否认“肝炎、肺结核”等传染病病史，否认“高",
            bbox=[699, 1306, 1535, 1349],
            confidence=0.99,
        ),
        IntelligentOcrBlock(
            page=1,
            text="肝炎、肺结核”等传染病病史，否认“高血压病、冠心病、",
            bbox=[946, 1311, 1795, 1347],
            confidence=0.98,
        ),
        IntelligentOcrBlock(
            page=1,
            text="糖尿病”等病史。3年前出现右侧腹股沟区有一椭圆形的可复",
            bbox=[630, 1364, 1535, 1406],
            confidence=0.99,
        ),
        IntelligentOcrBlock(
            page=1,
            text="手前出现右侧腹股沟区有一椭圆形的可复性肿块，站立时突",
            bbox=[945, 1363, 1800, 1408],
            confidence=0.98,
        ),
        IntelligentOcrBlock(
            page=1,
            text="出，可入同侧阴囊内，平卧位时消失，无不适症状，未到医院诊治。无外伤及手",
            bbox=[631, 1422, 1535, 1464],
            confidence=0.99,
        ),
        IntelligentOcrBlock(
            page=1,
            text="，平卧位时消失，无不适症状，未到医院诊治。无外伤及于",
            bbox=[946, 1423, 1790, 1464],
            confidence=0.98,
        ),
        IntelligentOcrBlock(
            page=1,
            text="血、骨痛，无淋巴结肿大等。",
            bbox=[626, 2055, 1072, 2095],
            confidence=0.99,
        ),
        IntelligentOcrBlock(
            page=1,
            text="种大等。",
            bbox=[945, 2052, 1075, 2097],
            confidence=0.98,
        ),
    ]

    deduped = _dedupe_ocr_blocks(blocks)

    assert [block.text for block in deduped] == [
        "现病史：患者于1年前无明显诱因开始出现左下腹痛，呈胀痛，尚可忍受，",
        "既往史：否认“肝炎、肺结核”等传染病病史，否认“高血压病、冠心病、",
        "糖尿病”等病史。3年前出现右侧腹股沟区有一椭圆形的可复性肿块，站立时突",
        "出，可入同侧阴囊内，平卧位时消失，无不适症状，未到医院诊治。无外伤及手",
        "血、骨痛，无淋巴结肿大等。",
    ]
    assert deduped[0].bbox == [706.0, 906.0, 1800.0, 948.0]


def test_rapidocr_same_line_near_duplicates_collapse():
    blocks = [
        IntelligentOcrBlock(
            page=1,
            text="现病史",
            bbox=[168, 748, 278, 786],
            confidence=0.96,
        ),
        IntelligentOcrBlock(
            page=1,
            text="患者于一年前,外地出差回家自觉全身乏力、食欲不振,先以",
            bbox=[258, 747, 1015, 807],
            confidence=0.91,
        ),
        IntelligentOcrBlock(
            page=1,
            text="患者于一年前，外地出差回家自觉全身乏力、食欲不振，先以",
            bbox=[287, 748, 1015, 807],
            confidence=0.93,
        ),
        IntelligentOcrBlock(
            page=1,
            text="红素51.3μmol/L，直接胆红素42.8μmol/l,ALT800U/L,HBsAg、HBeAg、",
            bbox=[118, 1268, 991, 1321],
            confidence=0.94,
        ),
        IntelligentOcrBlock(
            page=1,
            text="红素51.3μmol/L，直接胆红素42.8μmol/1，ALT800U/L,HBsAg、HBeAg、",
            bbox=[117, 1267, 991, 1322],
            confidence=0.92,
        ),
    ]

    deduped = _dedupe_ocr_blocks(blocks)

    assert [block.text for block in deduped] == [
        "现病史",
        "患者于一年前，外地出差回家自觉全身乏力、食欲不振，先以",
        "红素51.3μmol/L，直接胆红素42.8μmol/l,ALT800U/L,HBsAg、HBeAg、",
    ]


def test_rapidocr_fuzzy_covered_line_alternatives_are_suppressed():
    blocks = [
        IntelligentOcrBlock(
            page=6,
            text="①直肠癌根治术；②直肠癌切除，近端结肠造口，远端直肠封",
            bbox=[619, 1899, 1535, 1941],
            confidence=0.99113,
        ),
        IntelligentOcrBlock(
            page=6,
            text="手术）；③先行横结肠造口，再二期行直肠癌根治性切除术；④",
            bbox=[617, 1954, 1535, 1998],
            confidence=0.96582,
        ),
        IntelligentOcrBlock(
            page=6,
            text="则行姑息性横结肠造口。",
            bbox=[618, 2012, 979, 2054],
            confidence=0.99752,
        ),
        IntelligentOcrBlock(
            page=6,
            text="直肠癌切除，近端结肠造口，远端直肠封闭术（Hartmann",
            bbox=[945, 1898, 1788, 1942],
            confidence=0.99194,
        ),
        IntelligentOcrBlock(
            page=6,
            text="造口，再二期行直肠癌根治性切除术；④肿瘤不能切除者",
            bbox=[945, 1957, 1785, 1998],
            confidence=0.99187,
        ),
        IntelligentOcrBlock(
            page=6,
            text="。",
            bbox=[945, 2016, 984, 2062],
            confidence=0.99222,
        ),
        IntelligentOcrBlock(
            page=6,
            text="手术)；③先行横结肠造口，再二期行直肠癌根治性切除爪；",
            bbox=[620, 1972, 1500, 1999],
            confidence=0.93772,
        ),
        IntelligentOcrBlock(
            page=6,
            text="造口，再二期行直肠癌根治性切除爪；④肿瘤不能切除者",
            bbox=[945, 1972, 1782, 2000],
            confidence=0.95846,
        ),
    ]

    deduped = _dedupe_ocr_blocks(blocks)

    assert [block.text for block in deduped] == [
        "①直肠癌根治术；②直肠癌切除，近端结肠造口，远端直肠封闭术（Hartmann",
        "手术）；③先行横结肠造口，再二期行直肠癌根治性切除术；④肿瘤不能切除者",
        "则行姑息性横结肠造口。",
    ]


def test_rapidocr_fuzzy_overlap_stitches_without_repeating_middle_text():
    blocks = [
        IntelligentOcrBlock(
            page=6,
            text="肠减压；③纠正水电解质及酸碱平衡紊乱；④使用抗菌素；⑤",
            bbox=[620, 1789, 1535, 1825],
            confidence=0.94384,
        ),
        IntelligentOcrBlock(
            page=6,
            text="解质及酸碱平衡素乱；④使用抗菌素；⑤低压洗肠：⑥积极",
            bbox=[945, 1783, 1788, 1830],
            confidence=0.91044,
        ),
    ]

    deduped = _dedupe_ocr_blocks(blocks)

    assert [block.text for block in deduped] == [
        "肠减压；③纠正水电解质及酸碱平衡紊乱；④使用抗菌素；⑤低压洗肠：⑥积极"
    ]


def test_rapidocr_tile_fragments_use_visual_order_when_engine_order_is_inverted():
    blocks = [
        IntelligentOcrBlock(
            page=2,
            text="，今予办理出院。]",
            bbox=[1344, 3139, 1762, 3282],
            confidence=0.93,
        ),
        IntelligentOcrBlock(
            page=2,
            text="换，加强营养支持治疗，患者恢复可，今予办",
            bbox=[620, 3143, 1535, 3283],
            confidence=0.94,
        ),
        IntelligentOcrBlock(
            page=2,
            text="出院情况：[患者一般情况尚可，生命体征平科",
            bbox=[622, 3282, 1535, 3428],
            confidence=0.94,
        ),
    ]

    deduped = _dedupe_ocr_blocks(blocks)

    assert [block.text for block in deduped] == [
        "换，加强营养支持治疗，患者恢复可，今予办",
        "，今予办理出院。]",
        "出院情况：[患者一般情况尚可，生命体征平科",
    ]


def test_rapidocr_does_not_reverse_stitch_visually_ordered_tile_fragments():
    blocks = [
        IntelligentOcrBlock(
            page=2,
            text="今予办理出院。]",
            bbox=[100, 900, 420, 940],
            confidence=0.93,
        ),
        IntelligentOcrBlock(
            page=2,
            text="换，加强营养支持治疗，患者恢复可，今予办理",
            bbox=[430, 900, 900, 940],
            confidence=0.94,
        ),
    ]

    deduped = _dedupe_ocr_blocks(blocks)

    assert [block.text for block in deduped] == [
        "今予办理出院。]",
        "换，加强营养支持治疗，患者恢复可，今予办理",
    ]


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


def test_document_ir_block_accepts_ocr_provenance_fields():
    block = DocumentIRBlock(
        block_id="b1",
        page=1,
        reading_order=1,
        text="姓名：张三",
        model_name="PP-OCRv5",
        model_version="3.5.0",
        accelerator="directml",
        engine_version="ppocr-v5",
        route_profile_id="windows_radeon_balanced",
        stage_source="pp_ocr_v5",
        model_variant="server",
        render_dpi=300,
        preprocess_profile="document_orientation_unwarp",
        candidate_id="pp_ocr_v5:0001",
        candidate_group_id="p1:b1",
        conflict_flags=["text_conflict"],
    )

    assert block.model_name == "PP-OCRv5"
    assert block.accelerator == "directml"
    assert block.stage_source == "pp_ocr_v5"
    assert block.conflict_flags == ["text_conflict"]


def test_runtime_settings_expose_ocr_profile_and_accelerator(monkeypatch):
    monkeypatch.setattr(settings, "ocr_profile", "windows_radeon_balanced")
    client = TestClient(app)

    payload = client.get("/api/settings/runtime").json()["runtime_settings"]

    assert payload["ocr_active_profile"]["profile_id"] == "windows_radeon_balanced"
    assert payload["ocr_active_profile"]["pipeline_stages"] == [
        "preprocess",
        "pp_structure_v3",
        "pp_ocr_v5",
        "merge",
    ]
    assert payload["ocr_profile_engines"] == ["paddleocr_hybrid"]
    assert "ocr_accelerator" in payload
    assert "available_accelerators" in payload


def test_sidecar_health_exposes_profile_and_device(monkeypatch):
    monkeypatch.setattr(settings, "ocr_profile", "windows_radeon_balanced")
    monkeypatch.setattr(sidecar_main, "paddle_device_status", lambda: OcrDeviceStatus(requested="auto", resolved="cpu").model_dump())
    monkeypatch.setattr(sidecar_main, "accelerator_probe", lambda: {"directml": {"available": False}})
    monkeypatch.setattr(sidecar_main, "local_engines", lambda page_kind="image_ocr": [])

    payload = sidecar_main.health()

    assert payload["ocr_profile"]["profile_id"] == "windows_radeon_balanced"
    assert payload["api_contract_version"] == "eyex-ocr-sidecar-v2"
    assert payload["restart_message"].startswith("Restart OCR sidecar")
    assert payload["device"]["resolved"] == "cpu"
    assert payload["available_accelerators"]["directml"]["available"] is False


def test_probe_script_exists():
    assert Path("scripts/probe-amd-ocr.ps1").exists()
