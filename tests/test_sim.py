"""Simulator (docs/06 §5): dynamics, node emulation, faults, dataset."""

from datetime import UTC, datetime, timedelta

import pytest

from common.mqtt import Actuator, Command, encode
from edge.publisher import LoopbackBus, LoopbackPublisher
from sim.faults import Faults, parse_fault
from sim.model import ZoneModel, ZoneParams
from sim.nodes import ActuatorNode
from sim.simulation import Simulation
from sim.weather import Weather

T0 = datetime(2026, 7, 15, 0, 0, tzinfo=UTC)


def run_model(hours, act, params=None, start=T0):
    w, m = Weather(0), ZoneModel("z1", params or ZoneParams(emplacements=["z1-A1"]))
    t = start
    for _ in range(int(hours * 360)):
        t += timedelta(seconds=10)
        m.step(t, 10, w.step(t, 10), act)
    return m


def test_heating_ventilation_and_watering_effects():
    base = run_model(3, {})
    assert run_model(3, {Actuator.CHAUFFAGE: 1.0}).t > base.t + 5
    noon = T0 + timedelta(hours=10)
    assert run_model(1, {Actuator.VENTILO: 1.0}, start=noon).t < run_model(1, {}, start=noon).t
    assert run_model(0.1, {Actuator.POMPE_NUTRI: 1.0}).soil["z1-A1"] > base.soil["z1-A1"]


def test_hydro_dosing():
    p = ZoneParams(hydro=True)
    ph0 = run_model(0.1, {}, p).ph
    assert run_model(0.1, {Actuator.POMPE_PH_DOWN: 1.0}, p).ph < ph0 - 1
    assert run_model(0.1, {Actuator.POMPE_NUTRI_A: 1.0}, p).ec > run_model(0.1, {}, p).ec


def cmd(**kw):
    return encode(Command(ts=T0, source="test", **kw))


def test_actuator_node_firmware_logic():
    n = ActuatorNode("esp32-04", {"z2": [Actuator.POMPE_NUTRI, Actuator.VENTILO]}, pump_max_s=60)
    n.start(T0)
    n.drain()
    n.on_command("serre/z2/cmd/pompe_nutri", cmd(action="on"), T0)  # no duree_s
    n.on_command("serre/z2/cmd/pompe_nutri", cmd(action="on", duree_s=600), T0)  # > max
    assert len(n.refused) == 2 and n.level("z2", Actuator.POMPE_NUTRI) == 0
    n.on_command("serre/z2/cmd/pompe_nutri", cmd(action="on", duree_s=30), T0)
    assert n.level("z2", Actuator.POMPE_NUTRI) == 1.0
    n.step(T0 + timedelta(seconds=31))  # deadline
    assert n.level("z2", Actuator.POMPE_NUTRI) == 0.0
    n.tank["z2"] = 2.0
    n.on_command("serre/z2/cmd/pompe_nutri", cmd(action="on", duree_s=30), T0)
    assert n.level("z2", Actuator.POMPE_NUTRI) == 0.0  # local float switch
    n.on_command("serre/z2/cmd/ventilo", cmd(action="pwm", valeur=40), T0)
    assert n.level("z2", Actuator.VENTILO) == 0.4
    states = [t for t, _ in n.drain()]
    assert states.count("serre/z2/etat/pompe_nutri") == 2 and "serre/z2/etat/ventilo" in states


def test_fault_parsing_and_effects():
    f = parse_fault("fige:z1/temperature@30-90", T0)
    assert f.start == T0 + timedelta(minutes=30) and f.end == T0 + timedelta(minutes=90)
    with pytest.raises(ValueError):
        parse_fault("panne:z1", T0)
    faults = Faults([f, parse_fault("deconnexion:esp32-02@10-40", T0)])
    t = T0 + timedelta(minutes=31)
    assert faults.apply("z1", "temperature", 20.0, t) == 20.0
    assert faults.apply("z1", "temperature", 25.0, t + timedelta(minutes=5)) == 20.0  # frozen
    assert faults.apply("z1", "temperature", 25.0, T0 + timedelta(minutes=95)) == 25.0
    assert faults.disconnected("esp32-02", t) and not faults.disconnected("esp32-01", t)


def test_simulation_publishes_contract_topics():
    bus = LoopbackBus()
    faults = Faults([parse_fault("deconnexion:esp32-02@1-3", T0)])
    sim = Simulation(LoopbackPublisher("sim", bus), T0, faults=faults)
    sim.run(5 * 60)
    topics = {t for t, _ in bus.log}
    assert {
        "serre/z1/capteur/temperature",
        "serre/z1/capteur/presence",
        "serre/z1/capteur/pression",
        "serre/z1/capteur/humidite_sol",
        "serre/z2/capteur/ph",
        "serre/z2/etat/pompe_nutri",
    } <= topics
    status = [p for t, p in bus.log if t == "serre/esp32-02/status"]
    assert status == [b"online", b"offline", b"online"]
    assert bus.retained["serre/z1/etat/ventilo"]


def test_dataset_columns():
    from edge.controller.forecast import FEATURES, prepare
    from sim.dataset import generate

    df = generate(days=1, seed=0)
    assert set(df["zone"]) == {"z1", "z2"} and len(df) == 2 * 144
    assert (
        df.loc[df.zone == "z1", "ph"].isna().all() and df.loc[df.zone == "z2", "ph"].notna().all()
    )
    assert list(prepare(df[df.zone == "z2"].drop(columns="zone")).columns) == FEATURES
