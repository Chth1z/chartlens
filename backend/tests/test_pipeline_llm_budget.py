from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import CaseRecord, ProcessingRunRecord
from app.schemas.pipeline import EvidenceCandidate, FieldExtractionResult
from app.services.field_dictionary import FieldDefinition
from app.services.model_provider import ModelProvider
from app.services.pipeline import process_case


class RecordingProvider(ModelProvider):
    name = "recording"

    def __init__(self) -> None:
        self.field_keys: list[str] = []
        self.evidence_by_field: dict[str, list[EvidenceCandidate]] = {}
        self.last_usage: dict[str, int | float] = {
            "input_tokens": 123,
            "output_tokens": 45,
            "cached_input_tokens": 12,
            "cost_usd": 0.01,
        }

    def extract_fields(
        self,
        *,
        case_id: str,
        fields: list[FieldDefinition],
        evidence_by_field: dict[str, list[EvidenceCandidate]],
    ) -> list[FieldExtractionResult]:
        del case_id
        self.field_keys = [field.key for field in fields]
        self.evidence_by_field = evidence_by_field
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


def test_pipeline_sends_only_unresolved_configured_fields_to_provider(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    provider = RecordingProvider()
    payload = "性别：女\n年龄：67岁\n既往史：高血压病史10年。".encode("utf-8")
    case_file = tmp_path / "case.txt"
    case_file.write_bytes(payload)
    record = CaseRecord(
        case_id="CASE-PIPELINE",
        filename="case.txt",
        file_hash="hash-pipeline",
        file_path=str(case_file),
        status="queued",
    )
    session.add(record)
    session.commit()

    process_case(db=session, case=record, payload=payload, provider=provider)

    assert "gender" not in provider.field_keys
    assert "age" not in provider.field_keys
    assert "hypertension_history" not in provider.field_keys
    assert "diabetes_history" not in provider.field_keys
    assert "smoking_history" in provider.field_keys
    assert "__case_context__" in provider.evidence_by_field
    assert any("既往史" in item.text for item in provider.evidence_by_field["__case_context__"])
    session.refresh(record)
    run = session.query(ProcessingRunRecord).filter_by(case_id="CASE-PIPELINE").one()
    assert run.input_tokens == 123
    assert run.output_tokens == 45
    assert run.cached_input_tokens == 12
