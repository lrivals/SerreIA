"""Controller end to end on the in-memory bus: decision before command, traceability,
arbitration, safety refusals, alert latching; with the simulator (docs/06 §4–5, docs/10)."""

import json
from datetime import UTC, datetime

from common.mqtt import Command, Decision, decode, parse_raison
from edge.controller.service import Controller
from edge.publisher import LoopbackBus, LoopbackPublisher
from sim.faults import Faults, parse_fault
from sim.simulation import Simulation

from .controller_utils import NOON, feed, greenhouse, minutes, set_actuator


def controller():
    bus = LoopbackBus()
    ctl = Controller(greenhouse(), LoopbackPublisher("pi-controller", bus))
    ctl.subscribe()
    return ctl, bus


def messages(bus, kind):
    return [(t, decode(t, p)) for t, p in bus.log if f"/{kind}" in t]


def test_decision_precedes_command_and_is_referenced():
    ctl, bus = controller()
    feed(ctl.state, "z1", "temperature", 29.0, NOON)
    set_actuator(ctl.state, "z1", "ventilo", "off", NOON)
    out = ctl.tick(NOON)
    topics = [t for t, _ in out]
    i = topics.index("serre/z1/cmd/ventilo")
    decision = out[i - 1][1]
    assert isinstance(decision, Decision) and topics[i - 1] == "serre/z1/decision"
    cmd = out[i][1]
    assert isinstance(cmd, Command)
    dec_id, text = parse_raison(cmd.raison)
    assert dec_id == decision.id and "T°" in text
    assert decision.config_version == 1 and decision.statut == "executee"
    assert decision.actions == ["cmd:ventilo pwm 100 %"]
    published = [json.loads(p)["id"] for t, p in bus.log if t == "serre/z1/decision"]
    assert decision.id in published  # on the bus too

    # Same state at the next tick: nothing new (command pending, then confirmed).
    assert not [t for t, _ in ctl.tick(NOON + minutes(0.2)) if "/cmd/" in t]
    set_actuator(ctl.state, "z1", "ventilo", "pwm", NOON, 100)
    assert "serre/z1/cmd/ventilo" not in [t for t, _ in ctl.tick(NOON + minutes(1))]


def test_safety_off_wins_and_refusal_is_traced_once():
    ctl, _ = controller()
    feed(ctl.state, "z1", "temperature", 36.0, NOON)
    set_actuator(ctl.state, "z1", "chauffage", "on", NOON)
    out = ctl.tick(NOON)
    cmds = {t: m for t, m in out if "/cmd/" in t}
    assert cmds["serre/z1/cmd/chauffage"].action == "off"
    assert cmds["serre/z1/cmd/chauffage"].source == "safety"
    alerts = [m for t, m in out if t.endswith("/alerte")]
    assert any(a.niveau == "critique" for a in alerts)

    # Empty tank: the circulation cycle is refused, traced as bloquee_securite, once.
    feed(ctl.state, "z2", "niveau_cuve", 2.0, NOON, node="esp32-03")
    out = ctl.tick(NOON + minutes(1))
    blocked = [m for t, m in out if t == "serre/z2/decision" and m.statut == "bloquee_securite"]
    assert blocked and blocked[0].regle.id == "hydro.circulation"
    assert not [t for t, _ in out if t == "serre/z2/cmd/pompe_nutri"]
    feed(ctl.state, "z2", "niveau_cuve", 2.0, NOON + minutes(2), node="esp32-03")
    again = ctl.tick(NOON + minutes(2))
    assert not [m for t, m in again if t == "serre/z2/decision" and m.statut == "bloquee_securite"]


def test_alert_latched_then_end_reported():
    ctl, _ = controller()
    feed(ctl.state, "z2", "ph", 8.5, NOON, node="esp32-03")
    first = [m for t, m in ctl.tick(NOON) if t.endswith("/alerte")]
    assert [a.niveau for a in first if "pH" in a.message] == ["critique"]
    feed(ctl.state, "z2", "ph", 8.5, NOON + minutes(1), node="esp32-03")
    assert not [
        m for t, m in ctl.tick(NOON + minutes(1)) if t.endswith("/alerte") and "pH" in m.message
    ]
    feed(ctl.state, "z2", "ph", 6.0, NOON + minutes(2), node="esp32-03")
    end = [m for t, m in ctl.tick(NOON + minutes(2)) if t.endswith("/alerte")]
    assert any(a.niveau == "info" and "pH revenu" in a.message for a in end)


def test_simulation_with_controller_regulates():
    bus = LoopbackBus()
    gh = greenhouse()
    ctl = Controller(gh, LoopbackPublisher("pi-controller", bus))
    start = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)  # summer morning
    faults = Faults([parse_fault("cuve_vide:z2@60", start)])
    sim = Simulation(LoopbackPublisher("sim", bus), start, seed=1, faults=faults, controller=ctl)
    sim.run(3 * 3600)
    decisions = [m for _, m in messages(bus, "decision")]
    cmds = messages(bus, "cmd")
    assert decisions and cmds
    by_id = {d.id for d in decisions}
    assert all(parse_raison(c.raison)[0] in by_id for _, c in cmds)  # every command is traced
    assert messages(bus, "etat")  # the emulated actuator node confirmed the commands
    assert any(d.regle.id == "securite.cuve_vide" for d in decisions)
    assert sim.act_node.level("z2", "pompe_nutri") == 0.0  # pumps stopped on the empty tank
    t = sim.models["z1"].t
    assert 10 < t < 35
