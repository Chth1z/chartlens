from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.infrastructure.db.session import Base
from app.infrastructure.db.models import CaseRecord, ProcessingRunRecord
from app.domain.clinical import EvidenceCandidate, FieldExtractionResult
from app.domain.field_definitions import FieldDefinition
from app.application.model_provider import ModelProvider
from app.infrastructure.pipeline.case_processor import process_case


class RecordingProvider(ModelProvider):
    name = "recording"

    def __init__(self) -> None:
        self.call_count = 0
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
        self.call_count += 1
        self.field_keys.extend(field.key for field in fields)
        for key, candidates in evidence_by_field.items():
            self.evidence_by_field.setdefault(key, []).extend(candidates)
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


def test_pipeline_sends_only_unresolved_configured_fields_to_provider(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
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
    assert "smoking_history" not in provider.field_keys
    session.refresh(record)
    run = session.query(ProcessingRunRecord).filter_by(case_id="CASE-PIPELINE").one()
    assert run.step_timings["llm_skipped_no_evidence_count"] >= 1


def test_pipeline_sends_only_fields_with_evidence_to_llm_provider(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    provider = RecordingProvider()
    payload = "性别：女\n年龄：约六十岁\n既往史：一般健康状况可。".encode("utf-8")
    case_file = tmp_path / "case-with-llm-evidence.txt"
    case_file.write_bytes(payload)
    record = CaseRecord(
        case_id="CASE-PIPELINE-EVIDENCE",
        filename="case-with-llm-evidence.txt",
        file_hash="hash-pipeline-evidence",
        file_path=str(case_file),
        status="queued",
    )
    session.add(record)
    session.commit()

    process_case(db=session, case=record, payload=payload, provider=provider)

    assert provider.call_count >= 1
    assert "age" in provider.field_keys
    assert "smoking_history" not in provider.field_keys
    assert "__case_context__" in provider.evidence_by_field
    session.refresh(record)
    run = session.query(ProcessingRunRecord).filter_by(case_id="CASE-PIPELINE-EVIDENCE").one()
    assert run.input_tokens == 123 * provider.call_count
    assert run.output_tokens == 45 * provider.call_count
    assert run.cached_input_tokens == 12 * provider.call_count


def test_pipeline_demographics_use_homepage_fields_not_child_text(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    payload = "\n".join(
        [
            "姓名：小红 住址：A省B市C区XXXX路1号",
            "性别：女 联系人：小明",
            "年龄：60岁 工作单位：无",
            "婚姻史：已婚，配偶健康状况良好，家庭和睦，已有子女健康。",
        ]
    ).encode("utf-8")
    case_file = tmp_path / "case-homepage.txt"
    case_file.write_bytes(payload)
    record = CaseRecord(
        case_id="CASE-HOMEPAGE-DEMO",
        filename="case-homepage.txt",
        file_hash="hash-homepage-demo",
        file_path=str(case_file),
        status="queued",
    )
    session.add(record)
    session.commit()

    process_case(db=session, case=record, payload=payload, provider=RecordingProvider())

    results = {result.field_key: result for result in record.results}
    assert results["gender"].normalized_code == "2"
    assert results["gender"].evidence_text == "性别：女"
    assert results["age"].normalized_code == "60"
    assert results["age"].evidence_text == "年龄：60岁"


def test_pipeline_records_layout_fallback_diagnostics_for_text_cases(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    payload = "性别：女\n年龄：60岁\n既往史：一般健康状况可。".encode("utf-8")
    case_file = tmp_path / "case-layout-fallback.txt"
    case_file.write_bytes(payload)
    record = CaseRecord(
        case_id="CASE-LAYOUT-FALLBACK",
        filename="case-layout-fallback.txt",
        file_hash="hash-layout-fallback",
        file_path=str(case_file),
        status="queued",
    )
    session.add(record)
    session.commit()

    process_case(db=session, case=record, payload=payload, provider=RecordingProvider())

    run = session.query(ProcessingRunRecord).filter_by(case_id="CASE-LAYOUT-FALLBACK").one()
    assert run.step_timings["layout_provider"] == "fallback_heuristic"
    assert run.step_timings["layout_region_count"] >= 1
    assert run.step_timings["layout_cache_hit_count"] == 0
    assert run.step_timings["section_classifier_version"]
    assert run.step_timings["reading_order_strategy"] == "layout_region"
