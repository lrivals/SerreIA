"""FastAPI application: `create_app(sessions, publisher)`.

The database sessions and the MQTT publisher are injected, so that the tests run on
SQLite with the in-memory bus, and so is the agent (docs/11; a scripted LLM in the tests).
Only `POST /decisions/{id}/valider` and
`POST /actions/manuelle` publish towards the greenhouse (docs/12 §5): they publish a
`Decision` with the status `validee` on `serre/<zone>/decision`, the controller runs it
through `safety.py` (docs/10 §4). Nothing is ever published on `cmd/` from here.
"""

from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from . import actions, decisions
from . import agent as agent_routes


def create_app(
    sessions: sessionmaker[Session],
    publisher=None,
    clock: Callable[[], datetime] | None = None,
    agent=None,
) -> FastAPI:
    """`publisher`: edge.publisher.Publisher; None: read-only API (validation → 503).
    `agent`: backend.agent.loop.Agent; None: the /agent routes answer 503."""
    app = FastAPI(title="SerreIA", version="0.1.0")
    app.state.sessions = sessions
    app.state.publisher = publisher
    app.state.clock = clock or (lambda: datetime.now(UTC))
    app.state.agent = agent
    app.include_router(decisions.router)
    app.include_router(actions.router)
    app.include_router(agent_routes.router)
    return app
