from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from app.core.settings import settings


class Base(DeclarativeBase):
    pass


class CaseRecord(Base):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    filename: Mapped[str] = mapped_column(String(512))
    file_hash: Mapped[str] = mapped_column(String(128), index=True)
    file_path: Mapped[str] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(64), default="queued")
    raw_document_ir_json: Mapped[str | None] = mapped_column(Text, default=None)
    document_ir_json: Mapped[str | None] = mapped_column(Text, default=None)
    diagnostics_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    results: Mapped[list["FieldResultRecord"]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="FieldResultRecord.field_key",
    )
    audits: Mapped[list["ReviewAuditRecord"]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="ReviewAuditRecord.created_at",
    )


class FieldResultRecord(Base):
    __tablename__ = "field_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(String(64), ForeignKey("cases.case_id"), index=True)
    field_key: Mapped[str] = mapped_column(String(128), index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    reviewed: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    case: Mapped[CaseRecord] = relationship(back_populates="results")


class ReviewAuditRecord(Base):
    __tablename__ = "review_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(String(64), ForeignKey("cases.case_id"), index=True)
    field_key: Mapped[str] = mapped_column(String(128), index=True)
    before_json: Mapped[str] = mapped_column(Text)
    after_json: Mapped[str] = mapped_column(Text)
    reviewer: Mapped[str] = mapped_column(String(128), default="local_user")
    comment: Mapped[str | None] = mapped_column(Text, default=None)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    case: Mapped[CaseRecord] = relationship(back_populates="audits")


def _sqlite_path_from_url(url: str) -> Path | None:
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return None
    path = url.removeprefix(prefix)
    if path == ":memory:":
        return None
    return Path(path)


sqlite_path = _sqlite_path_from_url(settings.database_url)
if sqlite_path is not None:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    _ensure_sqlite_columns()


def _ensure_sqlite_columns() -> None:
    if sqlite_path is None:
        return
    with engine.begin() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(cases)").fetchall()}
        if "raw_document_ir_json" not in columns:
            connection.exec_driver_sql("ALTER TABLE cases ADD COLUMN raw_document_ir_json TEXT")


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def touch_case(case: CaseRecord) -> None:
    case.updated_at = datetime.now(timezone.utc)


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def get_case_or_none(db: Session, case_id: str) -> CaseRecord | None:
    return db.execute(select(CaseRecord).where(CaseRecord.case_id == case_id)).scalar_one_or_none()
