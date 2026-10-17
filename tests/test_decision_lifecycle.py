"""Life cycle of the decisions in the controller (docs/10 §4): proposed, validated,
rejected, expired; validated decisions through safety.py; captures, plant states and
temporary setpoints of the vision rules."""

from datetime import timedelta

from common.mqtt import CaptureRequest, Command, Decision, Ordre, decision_topic, decode, encode
from edge.controller.context import make_ctx
from edge.controller.service import Controller
from edge.publisher import LoopbackBus, LoopbackPublisher

from .controller_utils import (
    NOON,
    RIGHT,
    feed,
    feed_captures,
    feed_vision,
    greenhouse,
    minutes,
    vision,
)

LAST = NOON + minutes(20)


def controller():
    bus = LoopbackBus()
    ctl = Controller(greenhouse(), LoopbackPublisher("pi-controller", bus))
    ctl.subscribe()
    return ctl, bus


def decisions(out, statut=None):
    """Non-routine decisions (the photoperiod and the regulation run alongside)."""
    return [
        m
        for t, m in out
        if t.endswith("/decision") and m.type != "routine" and statut in (None, m.statut)
    ]


def answer(bus, d: Decision, statut: str, **update):
    """What the API publishes when the user answers a proposal."""
    msg = d.model_copy(update=dict(statut=statut, **update))
    LoopbackPublisher("backend-api", bus).publish(decision_topic(d.zone), msg)


def virus(ctl):
    feed_captures(ctl.state, "z1", "tomate/virus/mosaique", NOON)
    out = ctl.tick(LAST)
    (d,) = [d for d in decisions(out) if d.regle.id == "virus.isolement"]
    return d, out


def test_proposal_waits_then_runs_once_validated():
    ctl, bus = controller()
    d, out = virus(ctl)
    assert d.statut == "proposee" and d.expire == LAST + timedelta(hours=2)
    assert d.ordres == [Ordre(cible="plante:z1-A1", action="isolee")]
    assert d.actions == ["proposee:plante z1-A1 isolee", "alerte"]
    assert not [m for t, m in out if "/cmd/" in t and d.id in (m.raison or "")]
    assert any(t.endswith("/alerte") and m.niveau == "critique" for t, m in out)  # at once
    assert not decisions(ctl.tick(LAST + minutes(1)))  # latched: proposed once

    answer(bus, d, "validee")
    (done,) = decisions(ctl.tick(LAST + minutes(2)))
    assert done.id == d.id and done.statut == "executee"
    assert done.actions == ["plante:z1-A1 isolee"]
    assert d.id not in ctl.proposals
    answer(bus, d, "validee")  # redelivered (QoS 1): not run twice
    assert not decisions(ctl.tick(LAST + minutes(3)))


def test_rejected_proposal_is_not_proposed_again_while_the_condition_holds():
    ctl, bus = controller()
    d, _ = virus(ctl)
    answer(bus, d, "rejetee")
    assert d.id not in ctl.proposals
    feed_vision(ctl.state, "z1", vision(LAST + minutes(10), "tomate/virus/mosaique"))
    assert not decisions(ctl.tick(LAST + minutes(10)))
    # The condition ends (healthy captures), then comes back: proposed again.
    feed_captures(ctl.state, "z1", "tomate/sain/sain", LAST + minutes(20))
    ctl.tick(LAST + minutes(40))
    feed_captures(ctl.state, "z1", "tomate/virus/mosaique", LAST + minutes(50))
    again = decisions(ctl.tick(LAST + minutes(70)), "proposee")
    assert [x.regle.id for x in again] == ["virus.isolement"] and again[0].id != d.id


def test_proposal_expires():
    ctl, bus = controller()
    d, _ = virus(ctl)
    (exp,) = decisions(ctl.tick(LAST + timedelta(hours=2)), "expiree")
    assert exp.id == d.id and d.id not in ctl.proposals
    answer(bus, d, "validee")  # too late
    (late,) = decisions(ctl.tick(LAST + timedelta(hours=2, minutes=1)))
    assert late.statut == "expiree"


def test_validated_decision_goes_through_safety():
    ctl, bus = controller()
    feed(ctl.state, "z1", "presence", 1, NOON)  # somebody inside: no misting
    manual = Decision(
        id="dec-20260715-1000-z1-ui0001",
        ts=NOON,
        zone="z1",
        niveau="manuel",
        origine="ui:leonard",
        regle={"id": "manuel.ui", "version": 1},
        type="manuelle",
        explication="test → brumisateur on 60 s",
        actions=["proposee:brumisateur on 60 s", "proposee:ventilo on 600 s"],
        ordres=[
            Ordre(cible="actionneur:brumisateur", action="on", duree_s=60),
            Ordre(cible="actionneur:ventilo", action="on", duree_s=600, texte="aérer"),
        ],
        statut="validee",
    )
    LoopbackPublisher("backend-api", bus).publish(decision_topic("z1"), manual)
    out = ctl.tick(NOON + minutes(1))
    (d,) = [d for d in decisions(out) if d.id == manual.id]
    assert d.statut == "executee" and d.origine == "ui:leonard"
    assert d.actions[0] == "cmd:ventilo on 600 s"
    assert d.actions[1].startswith("bloquee:brumisateur on 60 s (securite.presence")
    cmds = [(t, m) for t, m in out if "/cmd/" in t and manual.id in (m.raison or "")]
    assert [t for t, _ in cmds] == ["serre/z1/cmd/ventilo"]
    cmd = cmds[0][1]
    assert isinstance(cmd, Command) and cmd.source == "ui"
    assert cmd.raison == f"{manual.id} | aérer"


def test_recapture_is_published_as_a_capture_request():
    ctl, _ = controller()
    feed_captures(ctl.state, "z1", "basilic/sain/sain", NOON, bbox=RIGHT, anomalie=0.9)
    out = ctl.tick(LAST)
    (d,) = decisions(out)
    assert d.regle.id == "vision.anomalie.recapture" and "capture:cam-z1-a" in d.actions
    (req,) = [m for t, m in out if t == "serre/z1/cmd/capture"]
    assert isinstance(req, CaptureRequest) and req.camera == "cam-z1-a"
    assert not [t for t, _ in ctl.tick(LAST + minutes(10)) if t.endswith("/cmd/capture")]
    later = ctl.tick(LAST + minutes(61))  # after recapture_s
    assert [t for t, _ in later if t.endswith("/cmd/capture")]


def test_mildew_lowers_the_humidity_setpoint_for_72_h():
    ctl, _ = controller()
    for at in (LAST - minutes(30), LAST):
        feed(ctl.state, "z1", "humidite", 92, at)
        feed(ctl.state, "z1", "temperature", 20, at)
    feed_captures(ctl.state, "z1", "tomate/maladie/mildiou", NOON)
    hi = ctl.greenhouse.setpoints["z1"].humidite[1]
    out = ctl.tick(LAST)
    (d,) = [d for d in decisions(out) if d.regle.id == "maladie.mildiou.plante"]
    assert d.statut == "executee"
    assert "plante:z1-A1 malade" in d.actions and "consigne:humidite max -10 pts 72 h" in d.actions
    assert ctl.state.zone("z1").consignes["humidite_max"][0] == -10
    # The regulation now compares the humidity with max − 10, for 72 h.
    assert make_ctx(ctl.greenhouse, ctl.state.zone("z1"), LAST).sp.humidite[1] == hi - 10
    assert not [x for x in decisions(ctl.tick(LAST + minutes(1))) if x.regle.id.startswith("mal")]
    later = make_ctx(ctl.greenhouse, ctl.state.zone("z1"), LAST + timedelta(hours=73))
    assert later.sp.humidite[1] == hi and not ctl.state.zone("z1").consignes


def test_decision_with_orders_round_trips():
    d, _ = virus(controller()[0])
    back = decode(decision_topic("z1"), encode(d))
    assert back.model_dump(mode="json") == d.model_dump(mode="json")
