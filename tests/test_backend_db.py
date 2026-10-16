"""Database of the greenhouse model (docs/09 §7): schema and seed from serre.yaml."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.db import models as m
from backend.db.seed import _grid, seed, serre_id
from edge.controller.config import load_greenhouse

from .backend_utils import T0, seeded_db


def count(s, model) -> int:
    return s.scalar(select(func.count()).select_from(model))


def test_seed_loads_the_configuration():
    _, sessions = seeded_db()
    with sessions() as s:
        serre = s.get(m.Serre, "maison")
        assert serre.fuseau == "Europe/Paris" and serre.tarif_kwh == 0.25
        assert serre.config_version == 1
        assert {z.id for z in s.scalars(select(m.Zone))} == {"z1", "z2"}
        assert s.get(m.Zone, "z2").cuve_id == "cuve-z2" and s.get(m.Zone, "z1").cuve_id is None
        a1 = s.get(m.Emplacement, "z1-A1")
        assert (a1.code, a1.mode_culture, a1.rangee, a1.colonne) == ("A1", "terre", 1, 1)
        tomate = s.get(m.Plante, "tomate-1")
        assert tomate.recette_id == "tomate-standard" and tomate.prioritaire
        assert "floraison" in s.get(m.Recette, "tomate-standard").stades
        led = s.get(m.Actionneur, "led-z1")
        assert (led.type, led.puissance_w, led.ppfd_max) == ("led", 240, 450)
        assert s.get(m.Actionneur, "arrosage-z1").debit_l_h == 120
        active = s.scalars(select(m.Affectation).where(m.Affectation.fin.is_(None))).all()
        assert {(a.plante_id, a.emplacement_id) for a in active} == {
            ("tomate-1", "z1-A1"),
            ("basilic-1", "z1-A2"),
            ("laitue-1", "z2-A1"),
        }


def test_seed_is_idempotent():
    _, sessions = seeded_db()
    with sessions.begin() as s:
        before = {t: count(s, t) for t in (m.Zone, m.Plante, m.Affectation, m.Actionneur)}
        seed(s, load_greenhouse(), T0 + timedelta(days=1))
    with sessions() as s:
        assert {t: count(s, t) for t in before} == before


def test_moving_a_plant_closes_its_assignment():
    _, sessions = seeded_db()
    gh = load_greenhouse()
    z1 = gh.cfg.zones[0]
    a1, a2 = z1.emplacements
    moved = z1.model_copy(
        update={
            "emplacements": [
                a1.model_copy(update={"plante": None}),
                a2.model_copy(update={"plante": a1.plante}),  # tomate-1 replaces basilic-1
            ]
        }
    )
    gh.cfg = gh.cfg.model_copy(update={"zones": [moved, gh.cfg.zones[1]]})
    later = T0 + timedelta(days=3)
    with sessions.begin() as s:
        seed(s, gh, later)
    with sessions() as s:
        rows = s.scalars(select(m.Affectation).order_by(m.Affectation.id)).all()
        active = {(a.plante_id, a.emplacement_id) for a in rows if a.fin is None}
        assert active == {("tomate-1", "z1-A2"), ("laitue-1", "z2-A1")}
        closed = {(a.plante_id, a.emplacement_id) for a in rows if a.fin is not None}
        assert closed == {("tomate-1", "z1-A1"), ("basilic-1", "z1-A2")}


def test_one_active_plant_per_emplacement():
    _, sessions = seeded_db()
    with pytest.raises(IntegrityError), sessions.begin() as s:
        s.add(m.Affectation(plante_id="basilic-1", emplacement_id="z1-A1", debut=T0))


def test_helpers():
    assert serre_id("Serre « Maison »") == "serre-maison"
    assert _grid("A1") == (1, 1) and _grid("B12") == (2, 12) and _grid("etagere-2") == (None, None)
