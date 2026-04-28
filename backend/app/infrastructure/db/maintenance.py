from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.infrastructure.db import models


CASE_RELATED_TABLES = [
    models.OcrBlockRecord,
    models.DocumentFragmentRecord,
    models.ExtractionResultRecord,
    models.ProcessingRunRecord,
    models.ModelCallLogRecord,
    models.VisionFallbackRequestRecord,
    models.ReviewAuditRecord,
]


def delete_case_record_tree(db: Session, case_id: str) -> int:
    for table in CASE_RELATED_TABLES:
        db.execute(delete(table).where(table.case_id == case_id))
    deleted_case = db.execute(delete(models.CaseRecord).where(models.CaseRecord.case_id == case_id)).rowcount or 0
    db.commit()
    return int(deleted_case)


def clear_case_record_tables(db: Session) -> int:
    case_count = db.query(models.CaseRecord).count()
    for table in CASE_RELATED_TABLES:
        db.execute(delete(table))
    db.execute(delete(models.CaseRecord))
    db.commit()
    return int(case_count)
