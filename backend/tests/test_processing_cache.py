from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import CaseRecord, ProcessingRunRecord
from app.services.pipeline import process_case


def test_process_case_reuses_cached_ocr_and_fragments_for_same_file_hash(tmp_path: Path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    payload = "性别：男\n年龄：62岁\n既往史：未见糖尿病相关记录。".encode("utf-8")

    first_file = tmp_path / "first.txt"
    second_file = tmp_path / "second.txt"
    first_file.write_bytes(payload)
    second_file.write_bytes(payload)

    first = CaseRecord(case_id="CASE-CACHE-1", filename="first.txt", file_hash="same-hash", file_path=str(first_file))
    second = CaseRecord(case_id="CASE-CACHE-2", filename="second.txt", file_hash="same-hash", file_path=str(second_file))
    session.add_all([first, second])
    session.commit()

    process_case(db=session, case=first, payload=payload)
    process_case(db=session, case=second, payload=payload)

    runs = session.query(ProcessingRunRecord).order_by(ProcessingRunRecord.created_at).all()
    assert runs[0].step_timings["cache_hit"] == 0
    assert runs[1].step_timings["cache_hit"] == 1
    assert runs[1].ocr_block_count == runs[0].ocr_block_count
    assert runs[1].fragment_count == runs[0].fragment_count
