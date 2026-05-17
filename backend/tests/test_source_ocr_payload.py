from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.core.database import CaseRecord, SessionLocal
from app.main import app
from app.services.secret_store import protect_text


def test_source_ocr_endpoint_uses_raw_document_ir_blocks_when_available():
    db = SessionLocal()
    case_id = "CASE-SOURCE-OCR-RAW"
    try:
        _cleanup_case(db, case_id)
        raw_payload = {
            "document_id": case_id,
            "profile_id": "medical_inpatient_zh",
            "source_filename": "case.pdf",
            "blocks": [
                {
                    "block_id": "b1",
                    "page": 1,
                    "reading_order": 1,
                    "text": "XXXX医院",
                    "bbox": [10, 20, 100, 40],
                    "confidence": 0.99,
                    "block_type": "line",
                    "source_engine": "pp_structure_v3",
                },
                {
                    "block_id": "b2",
                    "page": 1,
                    "reading_order": 2,
                    "text": "个人史",
                    "bbox": [10, 50, 80, 70],
                    "confidence": 0.98,
                    "block_type": "line",
                    "source_engine": "pp_structure_v3",
                },
                {
                    "block_id": "b3",
                    "page": 1,
                    "reading_order": 3,
                    "text": "pp_structure_v3:0038:9f07ff85",
                    "bbox": [],
                    "confidence": 0.5,
                    "block_type": "line",
                    "source_engine": "pp_structure_v3",
                },
            ],
            "sections": [],
            "metadata": {"ocr_engine": "paddleocr_hybrid"},
        }
        protected = protect_text(json.dumps(raw_payload, ensure_ascii=False))
        assert protected is not None
        case = CaseRecord(
            case_id=case_id,
            filename="case.pdf",
            file_hash="hash",
            file_path="case.pdf",
            status="completed",
            raw_document_ir_json=json.dumps(protected, ensure_ascii=False),
            document_ir_json=json.dumps({"blocks": [], "sections": [], "metadata": {}}, ensure_ascii=False),
        )
        db.add(case)
        db.commit()

        response = TestClient(app).get(f"/api/cases/{case_id}/source-ocr")

        assert response.status_code == 200
        payload = response.json()
        assert payload["metadata"]["source"] == "raw_document_ir"
        assert [block["text"] for block in payload["blocks"]] == ["XXXX医院", "个人史"]
        assert payload["blocks"][0]["bbox"] == [10, 20, 100, 40]
    finally:
        _cleanup_case(db, case_id)
        db.close()


def test_source_ocr_endpoint_prefers_layout_regions_for_boxed_source_view():
    db = SessionLocal()
    case_id = "CASE-SOURCE-OCR-LAYOUT"
    try:
        _cleanup_case(db, case_id)
        raw_payload = {
            "document_id": case_id,
            "profile_id": "medical_inpatient_zh",
            "source_filename": "case.pdf",
            "blocks": [
                {
                    "block_id": "b1",
                    "page": 1,
                    "reading_order": 1,
                    "text": "无框块",
                    "bbox": [],
                    "confidence": 0.99,
                    "block_type": "line",
                }
            ],
            "sections": [],
            "metadata": {
                "ocr_engine": "paddleocr_hybrid",
                "layout_regions": [
                    {
                        "layout_region_id": "layout:p1:0001",
                        "candidate_group_id": "p1:line:1",
                        "page": 1,
                        "text": "XXXX医院",
                        "bbox": [10, 20, 100, 40],
                        "block_type": "line",
                        "stage_source": "pp_structure_v3",
                        "confidence": 0.98,
                        "canonical_source_ids": ["pp_structure_v3:0001"],
                        "conflict_flags": [],
                        "merge_flags": ["canonical_selected"],
                    }
                ],
            },
        }
        protected = protect_text(json.dumps(raw_payload, ensure_ascii=False))
        assert protected is not None
        case = CaseRecord(
            case_id=case_id,
            filename="case.pdf",
            file_hash="hash",
            file_path="case.pdf",
            status="completed",
            raw_document_ir_json=json.dumps(protected, ensure_ascii=False),
            document_ir_json=json.dumps({"blocks": [], "sections": [], "metadata": {}}, ensure_ascii=False),
        )
        db.add(case)
        db.commit()

        response = TestClient(app).get(f"/api/cases/{case_id}/source-ocr")

        assert response.status_code == 200
        payload = response.json()
        assert payload["blocks"][0]["text"] == "XXXX医院"
        assert payload["blocks"][0]["bbox"] == [10, 20, 100, 40]
        assert payload["blocks"][0]["source_engine"] == "pp_structure_v3"
    finally:
        _cleanup_case(db, case_id)
        db.close()


def test_source_ocr_endpoint_preserves_numeric_boxed_values_from_candidates():
    db = SessionLocal()
    case_id = "CASE-SOURCE-OCR-NUMERIC"
    try:
        _cleanup_case(db, case_id)
        raw_payload = {
            "document_id": case_id,
            "profile_id": "medical_inpatient_zh",
            "source_filename": "case.pdf",
            "blocks": [],
            "sections": [],
            "metadata": {
                "ocr_engine": "paddleocr_hybrid",
                "raw_candidates": {
                    "pp_ocr_v5": [
                        {
                            "candidate_id": "pp_ocr_v5:age",
                            "page": 1,
                            "reading_order": 1,
                            "text": "16",
                            "bbox": [520, 130, 550, 155],
                            "confidence": 0.97,
                            "block_type": "line",
                            "source_engine": "pp_ocr_v5",
                        },
                        {
                            "candidate_id": "pp_ocr_v5:score",
                            "page": 1,
                            "reading_order": 2,
                            "text": "3",
                            "bbox": [420, 330, 438, 355],
                            "confidence": 0.95,
                            "block_type": "cell",
                            "source_engine": "pp_ocr_v5",
                        },
                    ]
                },
            },
        }
        protected = protect_text(json.dumps(raw_payload, ensure_ascii=False))
        assert protected is not None
        case = CaseRecord(
            case_id=case_id,
            filename="case.pdf",
            file_hash="hash",
            file_path="case.pdf",
            status="completed",
            raw_document_ir_json=json.dumps(protected, ensure_ascii=False),
            document_ir_json=json.dumps({"blocks": [], "sections": [], "metadata": {}}, ensure_ascii=False),
        )
        db.add(case)
        db.commit()

        response = TestClient(app).get(f"/api/cases/{case_id}/source-ocr")

        assert response.status_code == 200
        payload = response.json()
        assert payload["metadata"]["source"] == "raw_candidate_sets"
        assert [block["text"] for block in payload["blocks"]] == ["16", "3"]
        assert payload["blocks"][0]["bbox"] == [520, 130, 550, 155]
    finally:
        _cleanup_case(db, case_id)
        db.close()


def _cleanup_case(db: SessionLocal, case_id: str) -> None:
    case = db.query(CaseRecord).filter(CaseRecord.case_id == case_id).one_or_none()
    if case is not None:
        db.delete(case)
        db.commit()
