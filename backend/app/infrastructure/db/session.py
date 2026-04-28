from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from app.infrastructure.db import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_lightweight_columns()


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _ensure_lightweight_columns() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as connection:
        _ensure_column(connection, "processing_runs", "system_config_version", "TEXT DEFAULT ''")
        _ensure_column(connection, "processing_runs", "field_dictionary_version", "TEXT DEFAULT ''")
        _ensure_column(connection, "document_fragments", "layout_region_id", "TEXT")
        _ensure_column(connection, "document_fragments", "layout_type", "TEXT")
        _ensure_column(connection, "document_fragments", "section_confidence", "REAL DEFAULT 0")
        _ensure_column(connection, "document_fragments", "parser_version", "TEXT DEFAULT ''")
        for table_name in ("processing_runs", "model_call_logs"):
            _ensure_column(connection, table_name, "cached_input_tokens", "INTEGER DEFAULT 0")


def _ensure_column(connection, table_name: str, column_name: str, definition: str) -> None:
    rows = connection.exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()
    columns = {row[1] for row in rows}
    if rows and column_name not in columns:
        connection.exec_driver_sql(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
