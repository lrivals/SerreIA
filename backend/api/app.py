"""FastAPI application: `create_app(sessions, publisher)`.

The database sessions and the MQTT publisher are injected, so that the tests run on
SQLite with the in-memory bus, and so is the agent (docs/11; a scripted LLM in the tests).
Every route is under `/api` (docs/12 §3), the bus relay on `WS /ws/live`, and the built
front (`frontend/dist`) is served for every other path (single page application).

Only `POST /api/decisions/{id}/valider` and `POST /api/actions/manuelle` publish towards
the greenhouse (docs/12 §3): they publish a `Decision` with the status `validee` on
`serre/<zone>/decision`, the controller runs it through `safety.py` (docs/10 §4). Nothing
is ever published on `cmd/` from here. `POST /api/config/publier` installs a new serre.yaml.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, sessionmaker

from ..config.export import DEFAULT_OUT
from ..live.bridge import LiveHub
from . import (
    actions,
    alertes,
    auth,
    consommation,
    decisions,
    equipements,
    live,
    mesures,
    plantes,
    serres,
)
from . import agent as agent_routes
from . import config as config_routes

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "dist"


@dataclass
class Settings:
    password: str | None = None  # SERREIA_UI_PASSWORD: authentication of the writes
    images: Path = ROOT / "data" / "images"  # captures received from the camera_service
    config_out: Path = DEFAULT_OUT  # versions of serre.yaml
    config_install: Path | None = None  # local controller: serre.yaml replaced atomically
    config_rsync: str | None = None  # Pi: rsync destination of serre.yaml
    frontend: Path | None = FRONTEND


def create_app(
    sessions: sessionmaker[Session],
    publisher=None,
    clock: Callable[[], datetime] | None = None,
    agent=None,
    settings: Settings | None = None,
) -> FastAPI:
    """`publisher`: edge.publisher.Publisher; None: read-only API (validation → 503).
    `agent`: backend.agent.loop.Agent; None: the /agent routes answer 503."""
    settings = settings or Settings()
    app = FastAPI(title="SerreIA", version="0.1.0")
    app.state.sessions = sessions
    app.state.publisher = publisher
    app.state.clock = clock or (lambda: datetime.now(UTC))
    app.state.agent = agent
    app.state.settings = settings
    app.state.auth = auth.Auth(settings.password)
    app.state.live = None
    if publisher is not None and hasattr(publisher, "subscribe"):
        app.state.live = LiveHub()
        app.state.live.attach(publisher)

    api = APIRouter(prefix="/api", dependencies=[Depends(auth.check)])
    for module in (auth, serres, plantes, equipements, config_routes, mesures, consommation,
                   alertes, decisions, actions, agent_routes):  # fmt: skip
        api.include_router(module.router)
    app.include_router(api)
    app.include_router(live.router)
    if settings.frontend is not None and (settings.frontend / "index.html").is_file():
        _serve_front(app, settings.frontend.resolve())
    return app


def _serve_front(app: FastAPI, dist: Path) -> None:
    @app.get("/{path:path}", include_in_schema=False)
    def front(path: str) -> FileResponse:
        if path.split("/", 1)[0] in ("api", "ws"):
            raise HTTPException(404, f"route inconnue /{path}")
        file = (dist / path).resolve()
        if path and file.is_file() and file.is_relative_to(dist):
            return FileResponse(file)
        return FileResponse(dist / "index.html")  # client-side routes
