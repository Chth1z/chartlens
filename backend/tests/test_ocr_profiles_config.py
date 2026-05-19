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
from app.services.ocr_engine import engine_base as _engine_base
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
