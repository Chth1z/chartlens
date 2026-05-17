from pathlib import Path
import time

from app.core.settings import settings
from ocr_sidecar.main import engine_status, extract_with_engines, local_engines
from app.services.ocr_engine import IntelligentOcrBlock, IntelligentOcrResult


class MissingEngine:
    name = "missing"

    def available(self) -> bool:
        return False

    def unavailable_reason(self) -> str:
        return "missing dependency"

    def extract(self, file_path: Path) -> IntelligentOcrResult:
        raise AssertionError("unavailable engines must not run")


class LocalEngine:
    name = "local"

    def available(self) -> bool:
        return True

    def extract(self, file_path: Path) -> IntelligentOcrResult:
        return IntelligentOcrResult(
            engine="local_fixture",
            blocks=[IntelligentOcrBlock(page=2, text="姓名：张三", bbox=[1, 2, 3, 4], confidence=0.94, block_type="form_field")],
            metadata={"fixture": True},
        )


class SlowLocalEngine:
    name = "slow_local"

    def available(self) -> bool:
        return True

    def extract(self, file_path: Path) -> IntelligentOcrResult:
        time.sleep(0.05)
        return IntelligentOcrResult(
            engine="slow_local_fixture",
            blocks=[IntelligentOcrBlock(page=1, text="慢引擎结果", bbox=[0, 0, 10, 10], confidence=0.7)],
        )


def test_sidecar_extract_payload_preserves_blocks_and_unavailable_reasons(tmp_path):
    file_path = tmp_path / "case.pdf"
    file_path.write_bytes(b"%PDF fixture")

    payload = extract_with_engines(file_path, [MissingEngine(), LocalEngine()])

    assert payload["engine"] == "local_fixture"
    assert payload["blocks"] == [
        {
            "page": 2,
            "text": "姓名：张三",
            "bbox": [1, 2, 3, 4],
            "confidence": 0.94,
            "block_type": "form_field",
            "table_id": None,
            "row": None,
            "col": None,
            "row_span": 1,
            "col_span": 1,
            "stage_source": None,
            "candidate_id": None,
            "candidate_group_id": None,
            "conflict_flags": [],
            "canonical_source_ids": [],
            "layout_region_id": None,
            "line_group_id": None,
            "coordinate_system": None,
            "merge_confidence": None,
            "merge_flags": [],
            "model_name": None,
            "model_version": None,
            "model_variant": None,
            "render_dpi": None,
            "preprocess_profile": None,
        }
    ]
    assert payload["unavailable_engines"] == ["missing"]
    assert payload["unavailable_reasons"] == {"missing": "missing dependency"}
    assert payload["metadata"]["ocr_trace"]["selected_engine"] == "local_fixture"
    assert any(stage["engine"] == "local" and stage["status"] == "completed" for stage in payload["metadata"]["ocr_trace"]["stages"])


def test_sidecar_engine_status_only_reports_reason_when_unavailable():
    assert engine_status(MissingEngine()) == {
        "name": "missing",
        "available": False,
        "unavailable_reason": "missing dependency",
    }
    assert engine_status(LocalEngine()) == {
        "name": "local",
        "available": True,
        "unavailable_reason": "",
    }


def test_sidecar_default_engine_order_uses_hybrid_accuracy_pipeline(monkeypatch):
    monkeypatch.delenv("EYEX_OCR_SIDECAR_ENGINES", raising=False)
    monkeypatch.setattr(settings, "ocr_profile", "windows_radeon_balanced")

    assert [engine.name for engine in local_engines()] == ["paddleocr_hybrid"]


def test_sidecar_ignores_runtime_engine_override_env(monkeypatch):
    monkeypatch.setenv("EYEX_OCR_SIDECAR_ENGINES", "pp_ocr_v5_paddle,docling")
    monkeypatch.setattr(settings, "ocr_profile", "windows_radeon_balanced")

    assert [engine.name for engine in local_engines()] == ["paddleocr_hybrid"]


def test_sidecar_times_out_slow_engine_and_falls_back(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "ocr_engine_timeout_seconds", 0.01)
    file_path = tmp_path / "case.pdf"
    file_path.write_bytes(b"%PDF fixture")

    payload = extract_with_engines(file_path, [SlowLocalEngine(), LocalEngine()])

    assert payload["engine"] == "local_fixture"
    assert payload["engine_errors"]["slow_local"].startswith("[PAGE_TIMEOUT]")
    assert payload["metadata"]["ocr_trace"]["selected_engine"] == "local_fixture"
    assert any(stage["engine"] == "slow_local" and stage["status"] == "timeout" for stage in payload["metadata"]["ocr_trace"]["stages"])
    assert any(stage["engine"] == "local" and stage["status"] == "completed" for stage in payload["metadata"]["ocr_trace"]["stages"])
