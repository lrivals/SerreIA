"""MQTT → database ingestion service (docs/09 §7).

    python -m backend.ingestion                                  # broker localhost:1883
    python -m backend.ingestion --host pi.local --db postgresql+psycopg://…
    python -m backend.ingestion --sim --duree-h 24 --db sqlite:///serreia.db   # no broker

`--sim` runs the simulator and the controller in the same process on an in-memory bus,
on the simulated clock (demo and tests without broker nor Pi). The daily consumption of
the current and previous days is recomputed every hour (of simulated time with --sim).
"""

import argparse
import logging
import signal
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ..consumption import compute_day
from ..db.models import Serre
from ..db.seed import seed
from ..db.session import init_db, make_engine, make_sessions
from .mqtt_ingest import Ingestor

log = logging.getLogger("backend.ingestion")

NODE = "backend-ingestion"
CONSUMPTION_PERIOD = timedelta(hours=1)


class ConsumptionJob:
    """Recompute yesterday and today when `period` has elapsed on the given clock."""

    def __init__(self, sessions, period: timedelta = CONSUMPTION_PERIOD):
        self.sessions, self.period, self.next = sessions, period, None

    def maybe_run(self, now: datetime, force: bool = False) -> None:
        if not force and self.next is not None and now < self.next:
            return
        self.next = now + self.period
        try:
            with self.sessions.begin() as s:
                serre = s.scalars(select(Serre)).first()
                if serre is None:
                    return
                today = now.astimezone(ZoneInfo(serre.fuseau)).date()
                for jour in (today - timedelta(days=1), today):
                    totals = compute_day(s, jour, now)
                    log.info(
                        "consommation %s : %.3f kWh, %.1f L", jour, totals["kwh"], totals["litres"]
                    )
        except Exception:
            log.exception("calcul de consommation")


def run_sim(args, sessions) -> None:
    from edge.controller.config import DEFAULT_CONFIG
    from edge.controller.service import NODE as CONTROLLER
    from edge.controller.service import build
    from edge.publisher import LoopbackBus, LoopbackPublisher
    from sim.faults import Faults, parse_fault
    from sim.simulation import Simulation

    start = datetime.fromisoformat(args.debut) if args.debut else datetime.now(UTC)
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    bus = LoopbackBus()
    clock = {"t": start}
    ingestor = Ingestor(sessions, clock=lambda: clock["t"])
    ingestor.attach(bus)
    controller = build(args.config or DEFAULT_CONFIG, LoopbackPublisher(CONTROLLER, bus))
    faults = Faults([parse_fault(s, start) for s in args.panne])
    sim = Simulation(LoopbackPublisher("sim", bus), start, args.seed, faults, controller=controller)
    job = ConsumptionJob(sessions)
    end = start + timedelta(hours=args.duree_h) if args.duree_h else None
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    try:
        while (end is None or sim.t < end) and not stop.is_set():
            t_real = time.monotonic()
            sim.step()
            clock["t"] = sim.t
            job.maybe_run(sim.t)
            if args.accel:
                time.sleep(max(0.0, sim.dt / args.accel - (time.monotonic() - t_real)))
    except KeyboardInterrupt:
        pass
    finally:
        sim.close()
        ingestor.close()
        job.maybe_run(sim.t, force=True)
        log.info("%d messages ingérés, %d rejetés", ingestor.recus, ingestor.rejets)


def run_broker(args, sessions) -> None:
    from edge.publisher import MqttPublisher

    ingestor = Ingestor(sessions)
    client = MqttPublisher(NODE, args.host, args.port)
    ingestor.attach(client)
    job = ConsumptionJob(sessions)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    try:
        while not stop.wait(1.0):
            ingestor.flush()  # also when no message arrives
            job.maybe_run(datetime.now(UTC))
    except KeyboardInterrupt:
        pass
    finally:
        ingestor.close()
        client.close()
        log.info("%d messages ingérés, %d rejetés", ingestor.recus, ingestor.rejets)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", help="URL SQLAlchemy (défaut : $SERREIA_DB ou le compose)")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--seed-config", type=Path, help="charger ce serre.yaml au démarrage")
    parser.add_argument("--sim", action="store_true", help="simulateur + contrôleur intégrés")
    parser.add_argument("--accel", type=float, default=0.0, help="--sim : facteur (0 : max)")
    parser.add_argument("--duree-h", type=float, help="--sim : durée simulée (h)")
    parser.add_argument("--debut", help="--sim : date de début ISO (défaut : maintenant)")
    parser.add_argument("--seed", type=int, default=0, help="--sim : graine")
    parser.add_argument("--panne", action="append", default=[], help="--sim : sim/faults.py")
    parser.add_argument("--config", type=Path, help="--sim : serre.yaml du contrôleur")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    engine = make_engine(args.db)
    init_db(engine)
    sessions = make_sessions(engine)
    seed_config = args.seed_config or (args.config if args.sim else None)
    if args.sim and seed_config is None:
        from edge.controller.config import DEFAULT_CONFIG

        seed_config = DEFAULT_CONFIG
    if seed_config is not None:
        from edge.controller.config import load_greenhouse

        with sessions.begin() as s:
            seed(s, load_greenhouse(seed_config))
    (run_sim if args.sim else run_broker)(args, sessions)


if __name__ == "__main__":
    main()
