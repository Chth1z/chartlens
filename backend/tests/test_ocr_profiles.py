from __future__ import annotations

import sys
import types
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config_loader import load_ocr_profile, list_ocr_profiles
from app.core.settings import settings
from app.domain.models import DocumentIRBlock, OcrDeviceStatus
from app.main import app
from app.services import intelligent_ocr, ocr
from app.services.intelligent_ocr import (
    PPOCRV5OnnxDirectMLEngine,
    PPOCRV5PaddleEngine,
    default_intelligent_ocr_engines,
)
from ocr_sidecar import main as sidecar_main


def test_ocr_profiles_load_default_and_named_profiles():
    default_profile = load_ocr_profile("windows_radeon_balanced")
    profile_ids = {profile.profile_id for profile in list_ocr_profiles()}

    assert default_profile.profile_id == "windows_radeon_balanced"
    assert "pp_ocr_v5_paddle" in [engine.engine_id for engine in default_profile.engines]
    assert "cpu_stable" in profile_ids
    assert "cuda_paddle" in profile_ids
    assert "rocm_remote_vl" in profile_ids


def test_default_engine_order_comes_from_ocr_profile(monkeypatch):
    monkeypatch.setattr(settings, "ocr_profile", "windows_radeon_balanced")
    monkeypatch.setattr(settings, "ocr_document_ai_url", None)
    monkeypatch.setattr(intelligent_ocr, "load_ocr_profile", lambda profile_id=None: load_ocr_profile("windows_radeon_balanced"))

    names = [engine.name for engine in default_intelligent_ocr_engines(page_kind="image_ocr")]

    assert names[:3] == ["pp_ocr_v5_onnx_directml", "pp_ocr_v5_paddle", "paddle_structure_v3"]


def test_document_ai_sidecar_is_preferred_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "ocr_profile", "windows_radeon_balanced")
    monkeypatch.setattr(settings, "ocr_document_ai_url", "http://127.0.0.1:8765/extract")
    monkeypatch.setattr(intelligent_ocr, "load_ocr_profile", lambda profile_id=None: load_ocr_profile("windows_radeon_balanced"))

    names = [engine.name for engine in default_intelligent_ocr_engines(page_kind="image_ocr")]

    assert names[:4] == ["document_ai_http", "pp_ocr_v5_onnx_directml", "pp_ocr_v5_paddle", "paddle_structure_v3"]


def test_stale_engine_order_setting_does_not_override_ocr_profile(monkeypatch):
    monkeypatch.setattr(settings, "ocr_profile", "windows_radeon_balanced")
    monkeypatch.setattr(settings, "ocr_document_ai_url", "http://127.0.0.1:8765/extract")
    monkeypatch.setattr(intelligent_ocr, "load_ocr_profile", lambda profile_id=None: load_ocr_profile("windows_radeon_balanced"))

    names = [engine.name for engine in default_intelligent_ocr_engines(page_kind="image_ocr")]

    assert not hasattr(settings, "ocr_intelligent_engines")
    assert names[:4] == ["document_ai_http", "pp_ocr_v5_onnx_directml", "pp_ocr_v5_paddle", "paddle_structure_v3"]


def test_pp_ocr_v5_paddle_engine_uses_official_version_parameter(monkeypatch, tmp_path):
    calls = {}

    class FakePaddleOCR:
        def __init__(self, **kwargs):
            calls["init"] = kwargs

        def predict(self, input):
            calls["input"] = input
            return [{"rec_texts": ["既往史：否认高血压"], "rec_scores": [0.98]}]

    monkeypatch.setattr(intelligent_ocr, "_paddleocr_package_available", lambda: True)
    monkeypatch.setattr(intelligent_ocr, "_import_paddle_ocr_class", lambda: FakePaddleOCR)
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
    monkeypatch.setattr(intelligent_ocr, "_onnx_available_providers", lambda: ["CPUExecutionProvider"])
    (tmp_path / "det.onnx").write_bytes(b"det")
    (tmp_path / "rec.onnx").write_bytes(b"rec")

    engine = PPOCRV5OnnxDirectMLEngine()

    assert engine.available() is False
    assert "DmlExecutionProvider" in engine.unavailable_reason()


def test_directml_engine_enables_dml_for_detection_classification_and_recognition(monkeypatch, tmp_path):
    calls = {}

    class FakeOCRVersion:
        PPOCRV5 = "PP-OCRv5"

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

    fake_module = types.SimpleNamespace(RapidOCR=FakeRapidOCR, OCRVersion=FakeOCRVersion)
    monkeypatch.setitem(sys.modules, "rapidocr", fake_module)
    monkeypatch.setattr(intelligent_ocr.importlib.util, "find_spec", lambda name: object() if name == "rapidocr" else None)
    monkeypatch.setattr(intelligent_ocr, "_onnx_available_providers", lambda: ["DmlExecutionProvider", "CPUExecutionProvider"])
    monkeypatch.setattr(settings, "ocr_directml_model_dir", tmp_path)
    (tmp_path / "ch_PP-OCRv5_det_mobile.onnx").write_bytes(b"det")
    (tmp_path / "ch_PP-OCRv5_rec_mobile.onnx").write_bytes(b"rec")
    file_path = tmp_path / "page.png"
    file_path.write_bytes(b"image")

    result = PPOCRV5OnnxDirectMLEngine().extract(file_path)

    assert calls["params"]["Global.model_root_dir"] == str(tmp_path)
    assert calls["params"]["EngineConfig.onnxruntime.use_dml"] is True
    assert calls["params"]["Det.ocr_version"] == "PP-OCRv5"
    assert calls["params"]["Rec.ocr_version"] == "PP-OCRv5"
    assert result.metadata["accelerator"] == "directml"


def test_directml_engine_runs_pdf_pages_through_rendered_images(monkeypatch, tmp_path):
    calls = []

    class FakeOCRVersion:
        PPOCRV5 = "PP-OCRv5"

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

    fake_module = types.SimpleNamespace(RapidOCR=FakeRapidOCR, OCRVersion=FakeOCRVersion)
    monkeypatch.setitem(sys.modules, "rapidocr", fake_module)
    monkeypatch.setattr(intelligent_ocr.importlib.util, "find_spec", lambda name: object() if name == "rapidocr" else None)
    monkeypatch.setattr(intelligent_ocr, "_onnx_available_providers", lambda: ["DmlExecutionProvider", "CPUExecutionProvider"])
    monkeypatch.setattr(settings, "ocr_directml_model_dir", tmp_path)
    (tmp_path / "ch_PP-OCRv5_det_mobile.onnx").write_bytes(b"det")
    (tmp_path / "ch_PP-OCRv5_rec_mobile.onnx").write_bytes(b"rec")
    page_1 = tmp_path / "page-1.png"
    page_2 = tmp_path / "page-2.png"
    monkeypatch.setattr(intelligent_ocr, "_iter_rapidocr_page_inputs", lambda file_path: [(1, page_1), (2, page_2)])
    file_path = tmp_path / "case.pdf"
    file_path.write_bytes(b"%PDF fixture")

    result = PPOCRV5OnnxDirectMLEngine().extract(file_path)

    assert calls == [str(page_1), str(page_2)]
    assert [block.page for block in result.blocks] == [1, 2]
    assert [block.text for block in result.blocks] == ["page-1", "page-2"]


def test_ocr_cache_key_includes_engine_and_accelerator(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_dir", tmp_path)
    monkeypatch.setattr(settings, "ocr_profile", "windows_radeon_balanced")

    cpu_path = ocr._ocr_cache_path(b"same", page=1, engine_id="pp_ocr_v5_paddle", accelerator="cpu")
    directml_path = ocr._ocr_cache_path(b"same", page=1, engine_id="pp_ocr_v5_onnx_directml", accelerator="directml")

    assert cpu_path != directml_path


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
    )

    assert block.model_name == "PP-OCRv5"
    assert block.accelerator == "directml"


def test_runtime_settings_expose_ocr_profile_and_accelerator(monkeypatch):
    monkeypatch.setattr(settings, "ocr_profile", "windows_radeon_balanced")
    client = TestClient(app)

    payload = client.get("/api/settings/runtime").json()["runtime_settings"]

    assert payload["ocr_active_profile"]["profile_id"] == "windows_radeon_balanced"
    assert payload["ocr_profile_engines"][:3] == ["pp_ocr_v5_onnx_directml", "pp_ocr_v5_paddle", "paddle_structure_v3"]
    assert "ocr_accelerator" in payload
    assert "available_accelerators" in payload


def test_sidecar_health_exposes_profile_and_device(monkeypatch):
    monkeypatch.setattr(settings, "ocr_profile", "windows_radeon_balanced")
    monkeypatch.setattr(sidecar_main, "paddle_device_status", lambda: OcrDeviceStatus(requested="auto", resolved="cpu").model_dump())
    monkeypatch.setattr(sidecar_main, "accelerator_probe", lambda: {"directml": {"available": False}})
    monkeypatch.setattr(sidecar_main, "local_engines", lambda page_kind="image_ocr": [])

    payload = sidecar_main.health()

    assert payload["ocr_profile"]["profile_id"] == "windows_radeon_balanced"
    assert payload["device"]["resolved"] == "cpu"
    assert payload["available_accelerators"]["directml"]["available"] is False


def test_probe_script_exists():
    assert Path("scripts/probe-amd-ocr.ps1").exists()
