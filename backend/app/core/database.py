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
    from app import models  # noqa: F401

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
        for table_name in ("processing_runs", "model_call_logs"):
            rows = connection.exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()
            columns = {row[1] for row in rows}
            if rows and "cached_input_tokens" not in columns:
                connection.exec_driver_sql(
                    f"ALTER TABLE {table_name} ADD COLUMN cached_input_tokens INTEGER DEFAULT 0"
                )
