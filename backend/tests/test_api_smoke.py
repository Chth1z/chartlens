import json
import shutil
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from app.api.routes import _pdf_source_render_scale
from app.core.database import (
    CaseRecord,
    FieldResultRecord,
    ProcessingRunRecord,
    ReviewAuditRecord,
    SessionLocal,
    VisionFallbackRequestRecord,
)
from app.core.settings import settings
from app.domain.models import ValidatedFieldResult
from app.main import app


def test_health_endpoint():
    client = TestClient(app)
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_config_catalog_lists_active_profiles_and_paths():
    client = TestClient(app)

    response = client.get("/api/config/catalog")

    assert response.status_code == 200
    payload = response.json()
    assert payload["active"]["document_profile"] == settings.document_profile
    assert "medical_inpatient_zh" in payload["document_profiles"]
    assert "medical_inpatient_zh" in payload["extraction_schemas"]
    assert "medical_inpatient_zh" in payload["export_templates"]
    assert "windows_radeon_balanced" in payload["ocr_profiles"]
    assert payload["config_root"].endswith("config")


def test_config_artifact_returns_yaml_payload():
    client = TestClient(app)

    response = client.get("/api/config/document_profiles/medical_inpatient_zh")

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "document_profiles"
    assert payload["config_id"] == "medical_inpatient_zh"
    assert payload["parsed"]["profile_id"] == "medical_inpatient_zh"
    assert "extraction_system_prompt" in payload["yaml"]


def test_project_config_uses_active_document_profile(monkeypatch):
    monkeypatch.setattr(settings, "document_profile", "medical_inpatient_zh")
    client = TestClient(app)

    payload = client.get("/api/project-config").json()

    assert payload["app_profile"]["default_document_profile_id"] == settings.document_profile
    assert payload["document_profile"]["profile_id"] == settings.document_profile


def test_pdf_source_preview_scale_uses_ocr_block_render_dpi():
    case = CaseRecord(
        case_id="CASE-PDF",
        filename="case.pdf",
        file_hash="hash",
        file_path="case.pdf",
        document_ir_json=json.dumps(
            {
                "blocks": [
                    {"page": 1, "text": "第一页", "bbox": [10, 20, 30, 40], "render_dpi": 300},
                    {"page": 2, "text": "第二页", "bbox": [10, 20, 30, 40], "render_dpi": 240},
                    {"page": 3, "text": "第三页", "bbox": [10, 20, 30, 40], "render_dpi": 400},
                ]
            }
        ),
    )

    assert _pdf_source_render_scale(case, 1) == 300 / 72
    assert _pdf_source_render_scale(case, 2) == 240 / 72
    assert _pdf_source_render_scale(case, 3) == 400 / 72

    mixed_dpi_case = CaseRecord(
        case_id="CASE-PDF-MIXED-DPI",
        filename="case.pdf",
        file_hash="hash",
        file_path="case.pdf",
        document_ir_json=json.dumps(
            {
                "blocks": [
                    {"page": 1, "text": "第一页", "bbox": [800, 500, 2400, 700], "render_dpi": 400},
                    {"page": 1, "text": "第一页候选", "bbox": [600, 480, 1800, 680], "render_dpi": 300},
                ],
                "metadata": {"render_dpi": 300},
            }
        ),
    )

    assert _pdf_source_render_scale(mixed_dpi_case, 1) == 400 / 72


def test_source_page_endpoint_materializes_pdf_preview_at_ocr_dpi():
    db = SessionLocal()
    case_id = "CASE-SOURCE-PAGE-DPI"
    upload_dir = settings.storage_dir / "uploads" / case_id
    pdf_path = upload_dir / "case.pdf"
    try:
        _cleanup_case(db, case_id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        _write_test_pdf(pdf_path, width=72, height=144)
        db.add(
            CaseRecord(
                case_id=case_id,
                filename="case.pdf",
                file_hash="source-page-dpi",
                file_path=str(pdf_path),
                status="completed",
                document_ir_json=json.dumps(
                    {
                        "blocks": [
                            {"page": 1, "reading_order": 1, "text": "第一页", "bbox": [10, 20, 80, 60], "render_dpi": 400}
                        ],
                        "metadata": {"render_dpi": 300},
                    },
                    ensure_ascii=False,
                ),
            )
        )
        db.commit()
        client = TestClient(app)

        response = client.get(f"/api/cases/{case_id}/source-pages/1")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/png")
        assert response.headers["x-eyex-source-page-dpi"] == "400"
        image = Image.open(BytesIO(response.content))
        assert image.size == (400, 800)
        cached = list((settings.storage_dir / "source_pages" / case_id).glob("page-0001-dpi-400-*.png"))
        assert cached, "source preview must be materialized under project storage for stable reuse"
    finally:
        _cleanup_case(db, case_id)
        shutil.rmtree(settings.storage_dir / "uploads" / case_id, ignore_errors=True)
        shutil.rmtree(settings.storage_dir / "source_pages" / case_id, ignore_errors=True)
        db.close()


def test_source_page_endpoint_serves_cached_preview_when_original_missing():
    db = SessionLocal()
    case_id = "CASE-SOURCE-PAGE-CACHED"
    cache_dir = settings.storage_dir / "source_pages" / case_id
    cached_page = cache_dir / "page-0001-dpi-300-source-page-cached.png"
    try:
        _cleanup_case(db, case_id)
        cache_dir.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (300, 600), "white").save(cached_page)
        db.add(
            CaseRecord(
                case_id=case_id,
                filename="case.pdf",
                file_hash="source-page-cached",
                file_path=str(settings.storage_dir / "uploads" / case_id / "missing.pdf"),
                status="completed",
                document_ir_json=json.dumps(
                    {
                        "blocks": [
                            {"page": 1, "reading_order": 1, "text": "第一页", "bbox": [10, 20, 80, 60], "render_dpi": 300}
                        ],
                        "metadata": {"render_dpi": 300},
                    },
                    ensure_ascii=False,
                ),
            )
        )
        db.commit()
        client = TestClient(app)

        response = client.get(f"/api/cases/{case_id}/source-pages/1")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/png")
        assert response.headers["x-eyex-source-page-cache"] == "hit"
    finally:
        _cleanup_case(db, case_id)
        shutil.rmtree(settings.storage_dir / "source_pages" / case_id, ignore_errors=True)
        db.close()


def test_upload_text_case_end_to_end(monkeypatch):
    monkeypatch.setattr(settings, "llm_mode", "disabled")
    client = TestClient(app)
    response = client.post(
        "/api/cases",
        files={"file": ("case.txt", "基本信息：患者，男，66岁。\n\n既往史：否认高血压。".encode("utf-8"), "text/plain")},
    )

    assert response.status_code == 200
    case_id = response.json()["case_id"]

    # The background worker may still be running; synchronous reprocess gives deterministic smoke coverage.
    rerun = client.post(f"/api/cases/{case_id}/reprocess")
    assert rerun.status_code == 200

    results = client.get(f"/api/cases/{case_id}/results")
    assert results.status_code == 200
    by_key = {item["field_key"]: item for item in results.json()}
    assert by_key["gender"]["normalized_code"] == "1"
    assert by_key["hypertension_history"]["normalized_code"] == "0"


def test_delete_case_archives_and_preserves_runtime_records(tmp_path):
    db = SessionLocal()
    case_id = "CASE-DELETE-ARCHIVE"
    upload_dir = settings.storage_dir / "uploads" / case_id
    upload_path = upload_dir / "case.txt"
    try:
        _cleanup_case(db, case_id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        upload_path.write_text("病例原文", encoding="utf-8")
        db.add(
            CaseRecord(
                case_id=case_id,
                filename="case.txt",
                file_hash="hash",
                file_path=str(upload_path),
                status="completed",
            )
        )
        db.add(
            FieldResultRecord(
                case_id=case_id,
                field_key="hypertension_history",
                payload_json=ValidatedFieldResult(
                    field_key="hypertension_history",
                    field_group_key="history_group",
                    normalized_code="0",
                    status="confirmed",
                    review_required=False,
                ).model_dump_json(),
            )
        )
        db.add(
            ReviewAuditRecord(
                case_id=case_id,
                field_key="hypertension_history",
                before_json="{}",
                after_json="{}",
                reviewer="reviewer",
                comment="keep audit",
            )
        )
        db.add(
            ProcessingRunRecord(
                run_id=f"run-{case_id}",
                case_id=case_id,
                status="completed",
            )
        )
        db.commit()
        client = TestClient(app)

        response = client.delete(f"/api/cases/{case_id}")

        assert response.status_code == 200
        assert response.json()["message"] == "病例已从列表移除，原始文件和审计日志已保留。"
        assert upload_path.exists()
        archived = db.query(CaseRecord).filter(CaseRecord.case_id == case_id).one()
        assert archived.status == "archived"
        assert db.query(FieldResultRecord).filter(FieldResultRecord.case_id == case_id).count() == 1
        assert db.query(ReviewAuditRecord).filter(ReviewAuditRecord.case_id == case_id).count() == 1
        assert db.query(ProcessingRunRecord).filter(ProcessingRunRecord.case_id == case_id).count() == 1
        listed_ids = {item["case_id"] for item in client.get("/api/cases").json()}
        assert case_id not in listed_ids
    finally:
        _cleanup_case(db, case_id)
        db.close()


def test_vision_fallback_request_is_persisted_in_diagnostics():
    db = SessionLocal()
    case_id = "CASE-VISION-REQUEST"
    try:
        _cleanup_case(db, case_id)
        db.add(
            CaseRecord(
                case_id=case_id,
                filename="case.txt",
                file_hash="hash",
                file_path="case.txt",
                status="completed",
            )
        )
        db.commit()
        client = TestClient(app)

        response = client.post(
            f"/api/cases/{case_id}/vision-fallback-requests",
            json={
                "page": 3,
                "bbox": [10, 20, 30, 40],
                "field_key": "hh_grade",
                "reason": "当前字段需要图像模型复核原始页。",
                "reviewer": "local-reviewer",
                "manual_redaction_confirmed": True,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "recorded"
        assert payload["field_key"] == "hh_grade"
        assert db.query(VisionFallbackRequestRecord).filter(VisionFallbackRequestRecord.case_id == case_id).count() == 1
        diagnostics = client.get(f"/api/cases/{case_id}/diagnostics").json()
        assert diagnostics["vision_requests"][0]["request_id"] == payload["request_id"]
        assert diagnostics["vision_requests"][0]["bbox"] == [10, 20, 30, 40]
    finally:
        _cleanup_case(db, case_id)
        db.close()


def test_ocr_diagnostics_surface_debug_checks():
    db = SessionLocal()
    case_id = "CASE-OCR-DEBUG"
    try:
        _cleanup_case(db, case_id)
        document = {
            "blocks": [
                {"page": 1, "reading_order": 1, "text": "现病史：患者反复腹痛", "bbox": [10, 100, 1535, 130], "confidence": 0.91},
                {"page": 1, "reading_order": 2, "text": "患者反复腹痛伴恶心", "bbox": [900, 101, 1500, 131], "confidence": 0.90},
                {"page": 1, "reading_order": 3, "text": "患者反复腹痛伴恶心", "bbox": [902, 102, 1502, 132], "confidence": 0.89},
                {"page": 1, "reading_order": 4, "text": "姓名", "bbox": [10, 20, 60, 40], "confidence": 0.7},
                {"page": 1, "reading_order": 5, "text": "性别", "bbox": [120, 20, 170, 40], "confidence": 0.7},
                {"page": 1, "reading_order": 6, "text": "年龄", "bbox": [230, 20, 280, 40], "confidence": 0.7},
            ],
            "metadata": {
                "ocr_engine": "paddleocr_hybrid",
                "tile_max_side_len": 1536,
                "ocr_page_quality": [
                    {"page": 1, "char_count": 40, "avg_confidence": 0.72, "quality_band": "poor"}
                ],
            },
        }
        db.add(
            CaseRecord(
                case_id=case_id,
                filename="case.pdf",
                file_hash="hash",
                file_path="case.pdf",
                status="completed",
                document_ir_json=json.dumps(document, ensure_ascii=False),
            )
        )
        db.commit()
        client = TestClient(app)

        diagnostics = client.get(f"/api/cases/{case_id}/diagnostics").json()
        checks = {item["code"]: item for item in diagnostics["quality"]["ocr_debug"]["checks"]}

        assert "tile_boundary_crop_risk" in checks
        assert "line_fragmentation_risk" in checks
        assert "duplicate_text_risk" in checks
        assert "table_or_multicolumn_layout" in checks
        assert "low_quality_preprocess_needed" in checks
        assert diagnostics["quality"]["ocr_debug"]["recommended_profiles"]
    finally:
        _cleanup_case(db, case_id)
        db.close()


def _cleanup_case(db, case_id: str) -> None:
    db.query(VisionFallbackRequestRecord).filter(VisionFallbackRequestRecord.case_id == case_id).delete()
    db.query(ProcessingRunRecord).filter(ProcessingRunRecord.case_id == case_id).delete()
    db.query(ReviewAuditRecord).filter(ReviewAuditRecord.case_id == case_id).delete()
    db.query(FieldResultRecord).filter(FieldResultRecord.case_id == case_id).delete()
    db.query(CaseRecord).filter(CaseRecord.case_id == case_id).delete()
    db.commit()


def _write_test_pdf(path, *, width: int, height: int) -> None:
    image = Image.new("RGB", (width, height), "white")
    image.save(path, "PDF", resolution=72)
