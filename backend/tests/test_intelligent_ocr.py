from pathlib import Path
import time

from app.core.settings import settings
from app.domain.models import DocumentIRBlock
from app.services import ocr
from app.services.ocr_engine import IntelligentOcrBlock, IntelligentOcrResult, extract_with_intelligent_ocr
from app.services.ocr_engine.engines import HttpDocumentIntelligenceEngine
from app.services.ocr_engine.payload_parse import (
    _result_from_payload,
)


class UnavailableEngine:
    name = "unavailable"

    def available(self) -> bool:
        return False

    def unavailable_reason(self) -> str:
        return "missing fixture dependency"

    def extract(self, file_path: Path) -> IntelligentOcrResult:
        raise AssertionError("unavailable engines must not be called")


class WeakEngine:
    name = "weak"

    def available(self) -> bool:
        return True

    def extract(self, file_path: Path) -> IntelligentOcrResult:
        return IntelligentOcrResult(engine=self.name, blocks=[], metadata={"reason": "empty"})


class StrongEngine:
    name = "strong"

    def available(self) -> bool:
        return True

    def extract(self, file_path: Path) -> IntelligentOcrResult:
        return IntelligentOcrResult(
            engine=self.name,
            blocks=[
                IntelligentOcrBlock(page=1, text="姓名：张三", bbox=[10, 20, 100, 40], confidence=0.93, block_type="form_field"),
                IntelligentOcrBlock(
                    page=1,
                    text="手术名称",
                    bbox=[10, 60, 80, 80],
                    confidence=0.91,
                    block_type="cell",
                    table_id="t1",
                    row=1,
                    col=1,
                ),
            ],
            metadata={"layout_model": "fixture"},
        )


class SlowEngine:
    name = "slow"

    def available(self) -> bool:
        return True

    def extract(self, file_path: Path) -> IntelligentOcrResult:
        time.sleep(0.05)
        return IntelligentOcrResult(
            engine=self.name,
            blocks=[IntelligentOcrBlock(page=1, text="超时前的结果", bbox=[0, 0, 10, 10], confidence=0.8)],
        )


def test_intelligent_ocr_uses_first_sufficient_available_engine():
    blocks, metadata = extract_with_intelligent_ocr(
        Path("case.pdf"),
        {"未知": []},
        engines=[UnavailableEngine(), WeakEngine(), StrongEngine()],
    )

    assert metadata["ocr_engine"] == "strong"
    assert metadata["ocr_adapter"] == "intelligent_document"
    assert metadata["ocr_intelligent_status"] == "completed"
    assert metadata["ocr_attempted_engines"] == ["weak", "strong"]
    assert [item["route_engine"] for item in metadata["ocr_engine_candidates"]] == ["weak", "strong"]
    assert metadata["ocr_engine_candidates"][0]["sufficient"] is False
    assert metadata["ocr_engine_candidates"][1]["sufficient"] is True
    assert metadata["ocr_engine_candidates"][1]["alternative_blocks"][0]["text"] == "姓名：张三"
    assert len(blocks) == 2
    assert blocks[0].block_type == "form_field"
    assert blocks[0].text == "姓名：张三"
    assert blocks[1].block_type == "cell"
    assert blocks[1].table_id == "t1"
    assert blocks[1].row == 1
    assert blocks[1].col == 1
    assert metadata["ocr_trace"]["selected_engine"] == "strong"
    assert metadata["ocr_trace"]["result_block_count"] == 2
    assert any(stage["engine"] == "strong" and stage["status"] == "completed" for stage in metadata["ocr_trace"]["stages"])


def test_intelligent_ocr_returns_empty_result_when_no_engine_is_sufficient():
    blocks, metadata = extract_with_intelligent_ocr(Path("case.pdf"), {"未知": []}, engines=[UnavailableEngine(), WeakEngine()])

    assert blocks == []
    assert metadata["ocr_adapter"] == "intelligent_document"
    assert metadata["ocr_intelligent_status"] == "no_engine_result"
    assert metadata["ocr_attempted_engines"] == ["weak"]
    assert metadata["ocr_unavailable_engines"] == ["unavailable"]
    assert metadata["ocr_unavailable_reasons"] == {"unavailable": "missing fixture dependency"}
    assert metadata["ocr_trace"]["selected_engine"] == ""
    assert any(stage["engine"] == "unavailable" and stage["status"] == "skipped" for stage in metadata["ocr_trace"]["stages"])


def test_intelligent_ocr_times_out_slow_engine_and_falls_back(monkeypatch):
    monkeypatch.setattr(settings, "ocr_engine_timeout_seconds", 0.01)

    blocks, metadata = extract_with_intelligent_ocr(
        Path("case.pdf"),
        {"未知": []},
        engines=[SlowEngine(), StrongEngine()],
    )

    assert [block.text for block in blocks] == ["姓名：张三", "手术名称"]
    assert metadata["ocr_intelligent_status"] == "completed"
    assert metadata["ocr_engine_errors"]["slow"].startswith("[PAGE_TIMEOUT]")
    assert metadata["ocr_trace"]["selected_engine"] == "strong"
    assert any(stage["engine"] == "slow" and stage["status"] == "timeout" for stage in metadata["ocr_trace"]["stages"])
    assert any(stage["engine"] == "strong" and stage["status"] == "completed" for stage in metadata["ocr_trace"]["stages"])


class FakeHttpResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "engine": "sidecar_doc_ai",
            "blocks": [
                {
                    "page": 5,
                    "text": "姓名：张三",
                    "bbox": [10, 20, 100, 40],
                    "confidence": 0.94,
                    "block_type": "form_field",
                }
            ],
            "metadata": {
                "ocr_trace": {
                    "trace_id": "trace-sidecar-1",
                    "selected_engine": "sidecar_doc_ai",
                    "stages": [{"stage": "engine", "engine": "sidecar_doc_ai", "status": "completed"}],
                }
            },
        }


class EmptySidecarResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "engine": "none",
            "blocks": [],
            "attempted_engines": ["paddleocr_vl"],
            "unavailable_engines": ["docling"],
            "unavailable_reasons": {"docling": "missing docling"},
            "engine_errors": {"paddleocr_vl": "model download incomplete"},
        }


class SidecarErrorOnlyResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "engine": "none",
            "blocks": [],
            "attempted_engines": ["paddle_structure_v3"],
            "unavailable_engines": [],
            "engine_errors": {
                "paddle_structure_v3": "Error loading torch shm.dll",
            },
        }


class StaleSidecarHealthResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "ok": True,
            "engines": [],
        }


class SidecarKnownPrefixFailureResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "engine": "none",
            "blocks": [],
            "attempted_engines": ["pp_ocr_v5_onnx_directml"],
            "engine_errors": {
                "pp_ocr_v5_onnx_directml": "Unable to avoid copy while creating an array as requested. "
                "If using np.array(obj, copy=False) replace it with np.asarray(obj).",
            },
        }


class FakeHttpClient:
    def __init__(self):
        self.request = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def post(self, endpoint, *, headers, files, data):
        self.request = {
            "endpoint": endpoint,
            "headers": headers,
            "filename": files["file"][0],
            "profile_id": data["profile_id"],
        }
        return FakeHttpResponse()


class FakePaddleLayoutResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "result": {
                "layoutParsingResults": [
                    {
                        "prunedResult": {"text": "姓名：张三"},
                        "markdown": {"text": "## 入院记录\n姓名：张三\n| 项目 | 结果 |\n| 白细胞 | 8.6 |"},
                    }
                ]
            }
        }


class FakePaddleLayoutClient:
    def __init__(self):
        self.request = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def post(self, endpoint, *, headers, json):
        self.request = {
            "endpoint": endpoint,
            "headers": headers,
            "fileType": json["fileType"],
            "has_file": bool(json["file"]),
        }
        return FakePaddleLayoutResponse()


def test_http_document_intelligence_engine_posts_file_and_parses_blocks(tmp_path):
    file_path = tmp_path / "case.pdf"
    file_path.write_bytes(b"%PDF fixture")
    fake_client = FakeHttpClient()
    engine = HttpDocumentIntelligenceEngine(
        endpoint="http://127.0.0.1:8765/extract",
        api_key="secret",
        client_factory=lambda: fake_client,
    )

    result = engine.extract(file_path)

    assert fake_client.request == {
        "endpoint": "http://127.0.0.1:8765/extract",
        "headers": {"Authorization": "Bearer secret"},
        "filename": "case.pdf",
        "profile_id": "medical_inpatient_zh",
    }
    assert result.engine == "sidecar_doc_ai"
    assert len(result.blocks) == 1
    assert result.blocks[0].page == 5
    assert result.blocks[0].text == "姓名：张三"
    assert result.blocks[0].block_type == "form_field"
    assert result.metadata["ocr_trace"]["selected_engine"] == "sidecar_doc_ai"


def test_remote_paddleocr_vl_engine_supports_official_layout_parsing_api(tmp_path):
    file_path = tmp_path / "case.pdf"
    file_path.write_bytes(b"%PDF fixture")
    fake_client = FakePaddleLayoutClient()
    engine = HttpDocumentIntelligenceEngine(
        endpoint="http://127.0.0.1:8080/layout-parsing",
        api_key="secret",
        client_factory=lambda: fake_client,
    )

    result = engine.extract(file_path)

    assert fake_client.request == {
        "endpoint": "http://127.0.0.1:8080/layout-parsing",
        "headers": {"Authorization": "Bearer secret"},
        "fileType": 0,
        "has_file": True,
    }
    assert result.engine == "paddleocr_vl_remote:paddlex_layout"
    assert result.metadata["ocr_http_protocol"] == "paddlex_layout_parsing"
    assert result.metadata["raw_markdown"].startswith("## 入院记录")
    assert [block.text for block in result.blocks] == ["入院记录", "姓名：张三", "| 项目 | 结果 |", "| 白细胞 | 8.6 |"]


def test_http_document_intelligence_engine_exposes_sidecar_errors(tmp_path):
    file_path = tmp_path / "case.pdf"
    file_path.write_bytes(b"%PDF fixture")
    engine = HttpDocumentIntelligenceEngine(
        endpoint="http://127.0.0.1:8765/extract",
        client_factory=lambda: FakeHttpClientWithResponse(EmptySidecarResponse()),
    )

    blocks, metadata = extract_with_intelligent_ocr(file_path, {"未知": []}, engines=[engine])

    assert blocks == []
    assert metadata["ocr_attempted_engines"] == ["document_ai_http"]
    assert metadata["ocr_engine_errors"]["document_ai_http.paddleocr_vl"] == "model download incomplete"
    assert metadata["ocr_unavailable_reasons"]["document_ai_http.docling"] == "missing docling"


def test_http_document_intelligence_engine_does_not_treat_sidecar_errors_as_ocr_text(tmp_path):
    file_path = tmp_path / "case.pdf"
    file_path.write_bytes(b"%PDF fixture")
    engine = HttpDocumentIntelligenceEngine(
        endpoint="http://127.0.0.1:8765/extract",
        client_factory=lambda: FakeHttpClientWithResponse(SidecarErrorOnlyResponse()),
    )

    result = engine.extract(file_path)

    assert result.blocks == []
    assert result.metadata["ocr_http_engine_errors"] == {
        "paddle_structure_v3": "Error loading torch shm.dll",
    }


def test_http_document_intelligence_engine_rejects_stale_sidecar_health(tmp_path):
    file_path = tmp_path / "case.pdf"
    file_path.write_bytes(b"%PDF fixture")
    engine = HttpDocumentIntelligenceEngine(
        endpoint="http://127.0.0.1:8765/extract",
        client_factory=lambda: FakeHttpClientWithGetAndPost(
            StaleSidecarHealthResponse(),
            FakeHttpResponse(),
        ),
    )

    result = engine.extract(file_path)

    assert result.blocks == []
    assert result.metadata["ocr_http_engine_errors"] == {
        "sidecar_contract": "OCR sidecar is stale or incompatible; restart it with .\\stop.cmd, then .\\start.cmd so /health exposes api_contract_version=eyex-ocr-sidecar-v2."
    }
    assert result.metadata["ocr_http_restart_required"] is True


def test_http_document_intelligence_engine_flags_known_prefix_numpy_failure(tmp_path):
    file_path = tmp_path / "case.pdf"
    file_path.write_bytes(b"%PDF fixture")
    engine = HttpDocumentIntelligenceEngine(
        endpoint="http://127.0.0.1:8765/extract",
        client_factory=lambda: FakeHttpClientWithGetAndPost(
            {
                "ok": True,
                "api_contract_version": "eyex-ocr-sidecar-v2",
                "sidecar_build_id": "fixture-current",
            },
            SidecarKnownPrefixFailureResponse(),
        ),
    )

    result = engine.extract(file_path)

    assert result.blocks == []
    assert result.metadata["ocr_http_restart_required"] is True
    assert result.metadata["ocr_http_engine_errors"]["sidecar_stale_response"].startswith(
        "OCR sidecar returned a known pre-fix NumPy parsing failure"
    )


def test_paddle_structure_payload_uses_rec_texts_without_coordinate_noise():
    payload = [
        {
            "layout_det_res": {
                "boxes": [
                    {
                        "label": "text",
                        "score": 0.98,
                        "coordinate": ["83.42844", "764.7938", "1008.75244", "1410.1635"],
                    }
                ]
            },
            "overall_ocr_res": {
                "rec_texts": ["住院病历", "入院日期：2012-02-12"],
                "rec_scores": [0.99, 0.97],
                "rec_polys": [
                    [[10, 20], [100, 20], [100, 40], [10, 40]],
                    [[10, 50], [220, 50], [220, 70], [10, 70]],
                ],
            },
        }
    ]

    result = _result_from_payload("paddle_structure_v3", payload, default_confidence=0.86)

    assert [block.text for block in result.blocks] == ["住院病历", "入院日期：2012-02-12"]
    assert [block.confidence for block in result.blocks] == [0.99, 0.97]
    assert result.blocks[0].bbox == [10.0, 20.0, 100.0, 40.0]


class FakeHttpClientWithResponse:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def post(self, endpoint, *, headers, files, data):
        return self.response


class FakeHttpClientWithGetAndPost(FakeHttpClientWithResponse):
    def __init__(self, health_response, extract_response):
        super().__init__(extract_response)
        self.health_response = health_response

    def get(self, endpoint, *, headers):
        return self.health_response


def test_build_document_ir_routes_images_through_intelligent_ocr(monkeypatch, tmp_path):
    image_path = tmp_path / "case.png"
    image_path.write_bytes(b"not-a-real-image")

    def fake_intelligent_extract(file_path: Path, aliases):
        return [
            DocumentIRBlock(
                block_id="b0001-fixture",
                page=1,
                reading_order=1,
                text="姓名：张三",
                confidence=0.95,
                block_type="form_field",
            )
        ], {
            "ocr_adapter": "intelligent_document",
            "ocr_engine": "fixture_intelligent",
            "ocr_intelligent_status": "completed",
        }

    monkeypatch.setattr(settings, "ocr_strategy", "intelligent")
    monkeypatch.setattr(ocr, "extract_with_intelligent_ocr", fake_intelligent_extract)

    document_ir = ocr.build_document_ir(image_path, image_path.read_bytes(), document_id="case-fixture")

    assert document_ir.metadata["ocr_adapter"] == "intelligent_document"
    assert document_ir.metadata["ocr_engine"] == "fixture_intelligent"
    assert document_ir.blocks[0].text == "姓名：张三"


def test_build_document_ir_fails_when_intelligent_ocr_has_no_result(monkeypatch, tmp_path):
    image_path = tmp_path / "case.png"
    image_path.write_bytes(b"not-a-real-image")

    def fake_intelligent_extract(file_path: Path, aliases):
        return [], {
            "ocr_adapter": "intelligent_document",
            "ocr_engine": "none",
            "ocr_intelligent_status": "no_engine_result",
            "ocr_unavailable_engines": ["paddleocr_vl"],
            "ocr_unavailable_reasons": {"paddleocr_vl": "Python package 'paddleocr' is not installed"},
        }

    monkeypatch.setattr(settings, "ocr_strategy", "intelligent")
    monkeypatch.setattr(ocr, "extract_with_intelligent_ocr", fake_intelligent_extract)

    try:
        ocr.build_document_ir(image_path, image_path.read_bytes(), document_id="case-fixture")
    except RuntimeError as exc:
        assert "OCR_ENGINE_UNAVAILABLE" in str(exc)
        assert "reasons=paddleocr_vl=Python package 'paddleocr' is not installed" in str(exc)
    else:
        raise AssertionError("image OCR must fail when intelligent engines produce no result")
