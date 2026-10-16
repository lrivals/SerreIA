"""Simulated greenhouse behind the API (`python -m backend.api --mqtt sim`, docs/12 §5).

The simulator and the controller run in a background thread on an in-memory bus, with
the ingestion and the live relay attached: the whole UI works without a broker nor a Pi.
The simulation first catches up `prefill_h` hours at full speed (curves, decisions and
consumption are there from the start), then runs at `accel` × real time. The API clock
is the simulated clock. What the API publishes (validations, manual actions) is queued
and published by the simulation thread between two steps, so that the controller never
runs on two threads. `pannes`: faults of sim/faults.py, in minutes from the start of the
catch-up (e.g. a mildew seen on z1-A1, for a proposal to validate).
"""

import logging
import queue
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from edge.publisher import LoopbackBus, LoopbackPublisher

from ..ingestion.__main__ import ConsumptionJob
from ..ingestion.mqtt_ingest import Ingestor

log = logging.getLogger(__name__)


class QueuedPublisher:
    """The API side of the simulated bus: publications wait for the simulation thread."""

    def __init__(self, runner: "SimRunner"):
        self.runner = runner

    def publish(self, topic: str, message) -> None:
        self.runner.inbox.put((topic, message))

    def subscribe(self, pattern: str, handler) -> None:
        self.runner.bus.subscribe(pattern, handler)

    def close(self) -> None:
        pass


class SimRunner:
    def __init__(self, sessions, config: Path | None = None, accel: float = 1.0,
                 prefill_h: float = 24.0, seed: int = 0, pannes: list[str] = ()):  # fmt: skip
        from edge.controller.config import DEFAULT_CONFIG
        from edge.controller.service import NODE as CONTROLLER
        from edge.controller.service import build
        from sim.faults import Faults, parse_fault
        from sim.simulation import Simulation

        now = datetime.now(UTC).replace(microsecond=0)
        start = now - timedelta(hours=prefill_h)
        self.accel, self.live_from, self.start_t = accel, now, start
        self.sim = None
        self.bus = LoopbackBus()
        self.inbox: queue.Queue = queue.Queue()
        self.ingestor = Ingestor(sessions, clock=self.clock)
        self.ingestor.attach(self.bus)
        controller = build(config or DEFAULT_CONFIG, LoopbackPublisher(CONTROLLER, self.bus))
        faults = Faults([parse_fault(f, start) for f in pannes])
        self.sim = Simulation(
            LoopbackPublisher("sim", self.bus), start, seed, faults, controller=controller
        )
        self.api = LoopbackPublisher("backend-api", self.bus)
        self.job = ConsumptionJob(sessions)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, name="sim", daemon=True)

    def clock(self) -> datetime:
        return self.sim.t if self.sim is not None else self.start_t

    @property
    def publisher(self) -> QueuedPublisher:
        return QueuedPublisher(self)

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.stop.set()
        self.thread.join(timeout=5)
        self.sim.close()
        self.ingestor.close()

    def _run(self) -> None:
        log.info("simulation : rattrapage de %s à %s", self.sim.t, self.live_from)
        try:
            while not self.stop.is_set():
                t_real = time.monotonic()
                while not self.inbox.empty():
                    self.api.publish(*self.inbox.get_nowait())
                self.sim.step()
                self.job.maybe_run(self.sim.t)
                if self.sim.t >= self.live_from:
                    self.ingestor.flush()
                    pause = self.sim.dt / self.accel - (time.monotonic() - t_real)
                    self.stop.wait(max(0.0, pause))
        except Exception:
            log.exception("simulation arrêtée")
