from pathlib import Path

from app.core.settings import settings
from app.domain.models import DocumentIRBlock
from app.services import ocr
from app.services.intelligent_ocr import (
    HttpDocumentIntelligenceEngine,
    IntelligentOcrBlock,
    IntelligentOcrResult,
    extract_with_intelligent_ocr,
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


def test_intelligent_ocr_returns_empty_result_when_no_engine_is_sufficient():
    blocks, metadata = extract_with_intelligent_ocr(Path("case.pdf"), {"未知": []}, engines=[UnavailableEngine(), WeakEngine()])

    assert blocks == []
    assert metadata["ocr_adapter"] == "intelligent_document"
    assert metadata["ocr_intelligent_status"] == "no_engine_result"
    assert metadata["ocr_attempted_engines"] == ["weak"]
    assert metadata["ocr_unavailable_engines"] == ["unavailable"]
    assert metadata["ocr_unavailable_reasons"] == {"unavailable": "missing fixture dependency"}


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
