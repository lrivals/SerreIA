"""Helpers of the backend tests: an in-memory database seeded with serre.yaml."""

from datetime import UTC, datetime

from backend.db.seed import seed
from backend.db.session import init_db, make_engine, make_sessions
from edge.controller.config import load_greenhouse

T0 = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)  # 12:00 Europe/Paris


def seeded_db(url: str = "sqlite://", now: datetime = T0):
    engine = make_engine(url)
    init_db(engine)
    sessions = make_sessions(engine)
    with sessions.begin() as s:
        seed(s, load_greenhouse(), now)
    return engine, sessions
