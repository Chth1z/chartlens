from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.infrastructure.db.session import Base
from app.infrastructure.db.models import CaseRecord, ModelCallLogRecord, ProcessingRunRecord
from app.domain.clinical import EvidenceCandidate, FieldExtractionResult
from app.domain.field_definitions import FieldDefinition
from app.application.model_provider import ModelProvider
from app.infrastructure.pipeline.case_processor import process_case


class CountingProvider(ModelProvider):
    name = "counting"
    model = "counting-model"
    mode = "standard"

    def __init__(self) -> None:
        self.call_count = 0
        self.last_usage: dict[str, int | float] = {
            "input_tokens": 200,
            "output_tokens": 40,
            "cached_input_tokens": 0,
            "cost_usd": 0.02,
        }

    def extract_fields(
        self,
        *,
        case_id: str,
        fields: list[FieldDefinition],
        evidence_by_field: dict[str, list[EvidenceCandidate]],
    ) -> list[FieldExtractionResult]:
        del case_id, evidence_by_field
        self.call_count += 1
        return [
            FieldExtractionResult(
                field_key=field.key,
                raw_value=None,
                normalized_code="unknown",
                confidence=0.0,
                evidence_text=None,
                review_required=True,
                error_code="FAKE_LLM_MISS",
            )
            for field in fields
        ]


def test_pipeline_reuses_successful_llm_response_cache_for_same_redacted_evidence(tmp_path: Path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    provider = CountingProvider()
    payload = "性别：女\n年龄：约六十岁\n主诉：头痛1天。".encode("utf-8")

    records: list[CaseRecord] = []
    for index in range(2):
        case_file = tmp_path / f"case-{index}.txt"
        case_file.write_bytes(payload)
        record = CaseRecord(
            case_id=f"CASE-LLM-CACHE-{index}",
            filename=case_file.name,
            file_hash="same-llm-cache-hash",
            file_path=str(case_file),
            status="queued",
        )
        session.add(record)
        records.append(record)
    session.commit()

    process_case(db=session, case=records[0], payload=payload, provider=provider)
    first_call_count = provider.call_count
    process_case(db=session, case=records[1], payload=payload, provider=provider)

    second_run = (
        session.query(ProcessingRunRecord)
        .filter_by(case_id="CASE-LLM-CACHE-1")
        .order_by(ProcessingRunRecord.created_at.desc())
        .one()
    )
    second_calls = session.query(ModelCallLogRecord).filter_by(case_id="CASE-LLM-CACHE-1").all()

    assert first_call_count >= 1
    assert provider.call_count == first_call_count
    assert second_run.step_timings["llm_cache_hit"] == first_call_count
    assert second_run.step_timings["llm_call_count"] == 0
    assert {call.status for call in second_calls} == {"cache_hit"}
