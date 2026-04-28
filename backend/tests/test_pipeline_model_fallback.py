from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.infrastructure.db.session import Base
from app.infrastructure.db.models import CaseRecord, ModelCallLogRecord, ProcessingRunRecord
from app.domain.clinical import EvidenceCandidate, FieldExtractionResult
from app.domain.field_definitions import FieldDefinition
from app.application.model_provider import ModelProvider
from app.infrastructure.pipeline.case_processor import process_case


class FailingProvider(ModelProvider):
    name = "failing-online-provider"
    model = "failing-model"
    mode = "standard"
    last_usage: dict[str, int | float] = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}

    def extract_fields(
        self,
        *,
        case_id: str,
        fields: list[FieldDefinition],
        evidence_by_field: dict[str, list[EvidenceCandidate]],
    ) -> list[FieldExtractionResult]:
        del case_id, fields, evidence_by_field
        raise RuntimeError("simulated provider failure")


def test_pipeline_keeps_case_processed_when_online_model_fails(tmp_path: Path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    payload = "性别：女\n年龄：约六十岁\n既往史：糖尿病病史8年。".encode("utf-8")
    case_file = tmp_path / "case.txt"
    case_file.write_bytes(payload)
    record = CaseRecord(
        case_id="CASE-FALLBACK",
        filename="case.txt",
        file_hash="hash-fallback",
        file_path=str(case_file),
        status="queued",
    )
    session.add(record)
    session.commit()

    process_case(db=session, case=record, payload=payload, provider=FailingProvider())

    session.refresh(record)
    run = session.query(ProcessingRunRecord).filter_by(case_id="CASE-FALLBACK").one()
    calls = session.query(ModelCallLogRecord).filter_by(case_id="CASE-FALLBACK").all()
    assert record.status == "degraded"
    assert run.status == "degraded"
    assert calls
    assert {call.status for call in calls} == {"failed"}
    assert {call.error_code for call in calls} == {"PROVIDER_ERROR"}
    assert session.query(CaseRecord).filter_by(case_id="CASE-FALLBACK").one().results
