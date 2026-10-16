"""Configuration exported from the database to the controller (docs/09 §8)."""

import shutil
from datetime import timedelta

import pytest
import yaml
from sqlalchemy import select

from backend.config.export import build_config, export, install
from backend.db import models as m
from backend.db.seed import seed
from edge.controller.config import ConfigWatcher, SerreCfg, load_greenhouse

from .backend_utils import T0, seeded_db


def by_id(items: list[dict]) -> list[dict]:
    return sorted(items, key=lambda d: d["id"])


def test_round_trip_seed_then_export():
    _, sessions = seeded_db()
    with sessions.begin() as s:
        exp = export(s, T0)
    back = SerreCfg.model_validate(yaml.safe_load(exp.yaml()))
    orig = load_greenhouse().cfg
    assert back.config_version == exp.version == 2  # the seeded file is v1
    a = orig.model_dump(mode="json", exclude={"config_version", "recettes"})
    b = back.model_dump(mode="json", exclude={"config_version", "recettes"})
    for key in ("actionneurs", "capteurs", "cameras", "cuves"):  # the database sorts by id
        a[key], b[key] = by_id(a[key]), by_id(b[key])
    assert a == b
    assert back.load_recipes() == orig.load_recipes()  # inline: one self-contained file


def test_version_follows_the_content():
    _, sessions = seeded_db()
    with sessions.begin() as s:
        first = export(s, T0)
    with sessions.begin() as s:
        same = export(s, T0 + timedelta(hours=1))
    assert (first.version, first.changed) == (2, True)
    assert (same.version, same.changed) == (2, False)

    gh = load_greenhouse()  # the basil goes to a new emplacement
    z1 = gh.cfg.zones[0]
    a1, a2 = z1.emplacements
    a3 = a2.model_copy(update={"id": "z1-A3"})
    emptied = a2.model_copy(update={"plante": None})
    zones = [z1.model_copy(update={"emplacements": [a1, emptied, a3]}), *gh.cfg.zones[1:]]
    gh.cfg = gh.cfg.model_copy(update={"zones": zones})
    with sessions.begin() as s:
        seed(s, gh, T0 + timedelta(days=1))
    with sessions.begin() as s:
        moved = export(s, T0 + timedelta(days=1))
        assert s.get(m.Serre, "maison").config_version == 3
        assert [r.version for r in s.scalars(select(m.ConfigExport))] == [2, 3]
    assert moved.version == 3 and moved.changed
    emps = {e.id: e.plante for e in moved.cfg.zone("z1").emplacements}
    assert emps["z1-A2"] is None and emps["z1-A3"].id == "basilic-1"


def test_invalid_database_configuration_is_refused():
    _, sessions = seeded_db()
    with sessions.begin() as s:
        s.get(m.Plante, "tomate-1").stade = "dormance"  # no such stage in the recipe
    with sessions.begin() as s, pytest.raises(KeyError, match="dormance"):
        export(s, T0)
    with sessions() as s:
        assert s.scalars(select(m.ConfigExport)).all() == []


def test_channels_registered_by_the_ingestion_are_not_exported():
    _, sessions = seeded_db()
    with sessions.begin() as s:
        s.add(m.Capteur(id="esp32-09-lux", noeud="esp32-09", zone="z1", type="lux"))
    with sessions() as s:
        assert "esp32-09" not in {c["noeud"] for c in build_config(s)["capteurs"]}


def test_install_is_atomic_and_hot_reloaded(tmp_path):
    _, sessions = seeded_db()
    path = tmp_path / "serre.yaml"
    shutil.copy("edge/controller/serre.yaml", path)  # recipes path: relative to the repo
    watcher = ConfigWatcher(path)
    assert watcher.get().version == 1
    with sessions.begin() as s:
        exp = export(s, T0)
    install(exp.yaml(), path)
    watcher.mtime = 0  # same-second mtime
    assert watcher.get().version == 2
    assert [p.name for p in tmp_path.iterdir()] == ["serre.yaml"]  # no temporary file left
