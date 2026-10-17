"""Helpers of the API tests (docs/12): seeded SQLite, in-memory bus with the ingestion,
frozen clock, FastAPI test client."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from backend.api.app import Settings, create_app
from backend.ingestion.mqtt_ingest import Ingestor
from common.mqtt import encode
from edge.publisher import LoopbackBus, LoopbackPublisher

from .backend_utils import T0, seeded_db


@dataclass
class Api:
    client: TestClient
    bus: LoopbackBus
    ing: Ingestor
    sessions: object
    clock: dict = field(default_factory=dict)

    def send(self, topic: str, message) -> None:
        self.ing.on_message(topic, encode(message) if not isinstance(message, str) else message)
        self.ing.flush()

    def at(self, t: datetime) -> None:
        self.clock["t"] = t


def make_api(tmp_path, password: str | None = None, now: datetime = T0 + timedelta(minutes=5)):
    _, sessions = seeded_db()
    bus = LoopbackBus()
    clock = {"t": now}
    ing = Ingestor(sessions, clock=lambda: clock["t"])
    ing.attach(bus)
    settings = Settings(
        password=password,
        images=tmp_path / "images",
        config_out=tmp_path / "serre_config",
        config_install=tmp_path / "serre.yaml",
        frontend=None,
    )
    app = create_app(
        sessions, LoopbackPublisher("backend-api", bus), clock=lambda: clock["t"], settings=settings
    )
    return Api(TestClient(app), bus, ing, sessions, clock)
