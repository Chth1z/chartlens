from pathlib import Path

from app.core.settings import settings
from ocr_sidecar.main import engine_status, extract_with_engines, local_engines
from app.services.intelligent_ocr import IntelligentOcrBlock, IntelligentOcrResult


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
        }
    ]
    assert payload["unavailable_engines"] == ["missing"]
    assert payload["unavailable_reasons"] == {"missing": "missing dependency"}


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


def test_sidecar_default_engine_order_follows_active_profile_with_vl_as_last_fallback(monkeypatch):
    monkeypatch.delenv("EYEX_OCR_SIDECAR_ENGINES", raising=False)
    monkeypatch.setattr(settings, "ocr_profile", "windows_radeon_balanced")

    assert [engine.name for engine in local_engines()] == [
        "pp_ocr_v5_onnx_directml",
        "pp_ocr_v5_paddle",
        "paddle_structure_v3",
        "docling",
        "paddleocr_vl",
    ]
