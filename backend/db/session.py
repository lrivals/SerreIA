"""Engine, schema creation and dialect helpers.

The URL comes from `--db` or the `SERREIA_DB` environment variable; default: the
PostgreSQL + TimescaleDB of `backend/docker-compose.yml`. SQLite works too (tests, demo
without Docker): same tables, without hypertables.
"""

import os
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine, Table, create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base

DEFAULT_URL = "postgresql+psycopg://serreia:serreia@localhost:5432/serreia"
TIMESCALE_SQL = Path(__file__).with_name("timescale.sql")


def db_url(url: str | None = None) -> str:
    return url or os.environ.get("SERREIA_DB", DEFAULT_URL)


def make_engine(url: str | None = None) -> Engine:
    url = db_url(url)
    if url in ("sqlite://", "sqlite:///:memory:"):  # one shared in-memory database
        return create_engine(url, poolclass=StaticPool, connect_args={"check_same_thread": False})
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True)


def init_db(engine: Engine) -> None:
    """Create the missing tables and columns, then the hypertables on PostgreSQL
    (idempotent)."""
    Base.metadata.create_all(engine)
    add_missing_columns(engine)
    if engine.dialect.name != "postgresql":
        return
    statements = [s.strip() for s in _strip_comments(TIMESCALE_SQL.read_text()).split(";")]
    with engine.begin() as conn:
        for stmt in filter(None, statements):
            conn.exec_driver_sql(stmt)


def add_missing_columns(engine: Engine) -> list[str]:
    """`ALTER TABLE … ADD COLUMN` for the nullable columns added to the models since the
    table was created (e.g. `disposition`, docs/13 §3), until Alembic migrations exist."""
    existing = inspect(engine)
    added = []
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not existing.has_table(table.name):
                continue
            have = {c["name"] for c in existing.get_columns(table.name)}
            for col in table.columns:
                if col.name in have or not col.nullable:
                    continue
                kind = col.type.compile(dialect=engine.dialect)
                conn.exec_driver_sql(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {kind}')
                added.append(f"{table.name}.{col.name}")
    return added


def _strip_comments(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def make_sessions(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def insert(session: Session, table: Table):
    """Dialect `INSERT` supporting `on_conflict_do_nothing` / `on_conflict_do_update`."""
    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    else:
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    return dialect_insert(table)


def utc(ts: datetime) -> datetime:
    """Aware UTC datetime; SQLite gives back naive datetimes, stored in UTC."""
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)
