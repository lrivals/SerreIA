"""G1 validation on the PC (docs/07): the simulator and the controller ingested, daily
consumption computed — in memory, without broker nor TimescaleDB."""

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from backend.consumption import compute_day
from backend.db import models as m
from backend.ingestion.mqtt_ingest import Ingestor
from edge.controller.service import Controller
from edge.publisher import LoopbackBus, LoopbackPublisher
from sim.simulation import Simulation

from .backend_utils import seeded_db
from .controller_utils import greenhouse

START = datetime(2026, 7, 15, 6, 0, tzinfo=UTC)  # 08:00 Europe/Paris


def run(url: str, hours: float = 2.0):
    engine, sessions = seeded_db(url, START)
    bus = LoopbackBus()
    clock = {"t": START}
    ing = Ingestor(sessions, clock=lambda: clock["t"])
    ing.attach(bus)
    ctl = Controller(greenhouse(), LoopbackPublisher("pi-controller", bus))
    sim = Simulation(LoopbackPublisher("sim", bus), START, seed=1, controller=ctl)
    end = START.timestamp() + hours * 3600
    while sim.t.timestamp() < end:
        sim.step()
        clock["t"] = sim.t
    ing.close()
    with sessions.begin() as s:
        totals = compute_day(s, START.date(), now=sim.t)
    return engine, sessions, ing, bus, totals


def count(sessions, model, *where) -> int:
    with sessions() as s:
        return s.scalar(select(func.count()).select_from(model).where(*where))


def check(sessions, ing, bus, totals):
    assert ing.rejets == 0 and ing.recus == len(bus.log)
    assert count(sessions, m.Mesure) > 1000
    assert count(sessions, m.Mesure, m.Mesure.type == "humidite_sol") > 0
    assert count(sessions, m.EtatActionneur) > 0
    assert count(sessions, m.NoeudStatus, m.NoeudStatus.status == "online") >= 5
    assert count(sessions, m.Decision) > 0
    with sessions() as s:  # every command of a decision is traced back to it
        ids = set(s.scalars(select(m.Decision.id)))
        cmd_ids = set(
            s.scalars(select(m.Commande.decision_id).where(m.Commande.decision_id.isnot(None)))
        )
        assert cmd_ids and cmd_ids <= ids
        assert s.scalars(select(m.EtatActionneur.actionneur_id)).first() is not None
        assert {c.zone for c in s.scalars(select(m.Capteur))} == {"z1", "z2"}
        light = s.get(m.LumiereJour, (START.date(), "z1"))
        assert light.dli_total > 0
    assert totals["kwh"] > 0 and totals["litres"] >= 0


def test_simulator_ingested_and_consumption_computed():
    _, sessions, ing, bus, totals = run("sqlite://")
    check(sessions, ing, bus, totals)


@pytest.mark.skipif(not os.environ.get("SERREIA_TEST_PG"), reason="SERREIA_TEST_PG non défini")
def test_on_timescaledb():
    """Same scenario on a real PostgreSQL + TimescaleDB (`make stack-up`), e.g.
    SERREIA_TEST_PG=postgresql+psycopg://serreia:serreia@localhost:5432/serreia_test.
    The tables of that database are dropped first."""
    from backend.db.session import make_engine

    url = os.environ["SERREIA_TEST_PG"]
    m.Base.metadata.drop_all(make_engine(url))
    engine, sessions, ing, bus, totals = run(url, hours=1.0)
    check(sessions, ing, bus, totals)
    with engine.connect() as conn:
        hypertables = set(
            conn.exec_driver_sql(
                "SELECT hypertable_name FROM timescaledb_information.hypertables"
            ).scalars()
        )
    assert {"mesure", "etat_actionneur", "vision_resultat"} <= hypertables
