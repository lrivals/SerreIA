"""Server side of the traceability (docs/10 §3–6): actions derived from the decisions and
commands, confirmation by etat/, plant states, end of the decisions, action tree."""

from datetime import timedelta

from sqlalchemy import select

from backend.db import models as m
from backend.ingestion.mqtt_ingest import Ingestor
from backend.traceability import action_id, build_tree, parse_label, render_text
from common.mqtt import (
    ActuatorState,
    Command,
    Decision,
    Ordre,
    capture_topic,
    cmd_topic,
    command_raison,
    decision_topic,
    encode,
    state_topic,
    vision_topic,
)
from common.mqtt.schemas import CaptureRequest

from .backend_utils import T0, seeded_db
from .controller_utils import vision


def ingestor(start=T0):
    _, sessions = seeded_db()
    clock = {"t": start}
    ing = Ingestor(sessions, clock=lambda: clock["t"])
    return ing, sessions, clock


def send(ing, topic, msg):
    ing.on_message(topic, encode(msg))


def decision(n=1, ts=T0, type_="exceptionnelle", actions=(), statut="executee", **kw):
    return Decision(
        id=f"dec-20260715-1000-z1-{n:03d}",
        ts=ts,
        zone="z1",
        niveau=1,
        origine="controller",
        regle={"id": kw.pop("regle", "maladie.mildiou.ventilation"), "version": 1},
        type=type_,
        explication=kw.pop("explication", "HR > 90 % depuis 11 h → ventilation 15 min"),
        actions=list(actions),
        statut=statut,
        **kw,
    )


def command(d, ts, action="on", duree_s=None, actuator="ventilo", valeur=None):
    return (
        cmd_topic("z1", actuator),
        Command(
            ts=ts,
            action=action,
            valeur=valeur,
            duree_s=duree_s,
            source="controller",
            raison=command_raison(d.id, "test"),
        ),  # fmt: skip
    )


def actions(sessions, did=None):
    with sessions() as s:
        q = select(m.Action).order_by(m.Action.id)
        if did:
            q = q.where(m.Action.decision_id == did)
        return list(s.scalars(q))


def statut(sessions, did):
    with sessions() as s:
        return s.get(m.Decision, did).statut


def test_labels():
    assert parse_label("cmd:ventilo pwm 100 % 900 s") == (
        "actionneur:ventilo", "ventilo pwm 100 % 900 s", "en_attente"
    )  # fmt: skip
    assert parse_label("bloquee:pompe_nutri on 600 s (securite.cuve_vide)")[2] == "bloquee"
    assert parse_label("alerte") == ("alerte", "alerte", "confirmee")
    assert parse_label("capture:cam-z1-a")[0] == "camera:cam-z1-a"
    assert parse_label("plante:z1-A1 malade") == (
        "plante:z1-A1",
        "plante z1-A1 malade",
        "en_attente",
    )
    assert parse_label("proposee:plante z1-A1 isolee")[::2] == ("plante:z1-A1", "proposee")
    assert parse_label("proposee:ventilo on 900 s")[::2] == ("actionneur:ventilo", "proposee")
    assert action_id("dec-20261012-0231-z1-007", 1) == "act-20261012-0231-z1-007-01"


def test_action_confirmed_by_state_then_decision_over():
    ing, sessions, clock = ingestor()
    d = decision(actions=["cmd:ventilo on 900 s", "alerte"])
    send(ing, decision_topic("z1"), d)
    send(ing, *command(d, T0, duree_s=900))
    send(
        ing, state_topic("z1", "ventilo"), ActuatorState(ts=T0 + timedelta(seconds=2), action="on")
    )
    ing.flush()
    act, alert = actions(sessions, d.id)
    assert act.id == action_id(d.id, 1) and act.cible == "actionneur:ventilo"
    assert act.resultat == "confirmee" and act.commande["duree_s"] == 900
    assert act.ts_fin.replace(tzinfo=None) == (T0 + timedelta(seconds=900)).replace(tzinfo=None)
    assert alert.cible == "alerte" and alert.resultat == "confirmee"
    assert act.type == "exceptionnelle" and act.zone == "z1"
    assert statut(sessions, d.id) == "executee"  # the fan still runs
    clock["t"] = T0 + timedelta(seconds=901)
    ing.flush()  # nothing new to write: reconcile still runs on the next batch
    send(ing, state_topic("z1", "ventilo"), ActuatorState(ts=clock["t"], action="off"))
    ing.flush()
    assert statut(sessions, d.id) == "terminee"


def test_action_without_state_is_not_confirmed():
    ing, sessions, clock = ingestor()
    d = decision(actions=["cmd:chauffage on"])
    send(ing, decision_topic("z1"), d)
    send(ing, *command(d, T0, actuator="chauffage"))
    ing.flush()
    assert actions(sessions)[0].resultat == "en_attente"
    clock["t"] = T0 + timedelta(seconds=30)
    send(ing, state_topic("z1", "led"), ActuatorState(ts=clock["t"], action="off"))  # unrelated
    ing.flush()
    assert actions(sessions)[0].resultat == "non_confirmee"
    assert statut(sessions, d.id) == "terminee"  # nothing more will happen


def test_untimed_action_ends_with_the_next_command():
    ing, sessions, clock = ingestor()
    d1 = decision(1, type_="routine", regle="climat.temperature.ventilation",
                  actions=["cmd:ventilo pwm 100 %"])  # fmt: skip
    send(ing, decision_topic("z1"), d1)
    send(ing, *command(d1, T0, action="pwm", valeur=100))
    send(ing, state_topic("z1", "ventilo"), ActuatorState(ts=T0, action="pwm", valeur=100))
    ing.flush()
    assert actions(sessions)[0].ts_fin is None and statut(sessions, d1.id) == "executee"
    t1 = T0 + timedelta(minutes=40)
    clock["t"] = t1
    d2 = decision(2, ts=t1, type_="routine", regle="climat.temperature.ventilation",
                  actions=["cmd:ventilo off"])  # fmt: skip
    send(ing, decision_topic("z1"), d2)
    send(ing, *command(d2, t1, action="off"))
    send(ing, state_topic("z1", "ventilo"), ActuatorState(ts=t1, action="off"))
    ing.flush()
    first, second = actions(sessions)
    assert first.ts_fin.replace(tzinfo=None) == t1.replace(tzinfo=None)
    assert second.resultat == "confirmee"
    assert statut(sessions, d1.id) == statut(sessions, d2.id) == "terminee"

    tree = build_tree(sessions(), T0, T0 + timedelta(hours=1))
    z1 = next(z for z in tree["children"] if z["id"] == "z1")
    (routines,) = z1["children"]
    (node,) = routines["children"]
    assert node["cycles"] == 2 and node["duree_on_s"] == 40 * 60 and node["echecs"] == 0
    assert node["label"] == "climat.temperature.ventilation ventilo"


def test_plant_state_and_capture_actions():
    ing, sessions, clock = ingestor()
    d = decision(actions=["alerte", "capture:cam-z1-a", "plante:z1-A1 malade",
                          "consigne:humidite max -10 pts 72 h"])  # fmt: skip
    send(ing, decision_topic("z1"), d)
    send(ing, capture_topic("z1"), CaptureRequest(ts=T0, source="controller", camera="cam-z1-a"))
    ing.flush()
    by_cible = {a.cible: a for a in actions(sessions)}
    assert by_cible["plante:z1-A1"].resultat == "confirmee"
    assert by_cible["camera:cam-z1-a"].resultat == "en_attente"
    assert by_cible["consigne"].resultat == "confirmee"
    with sessions() as s:
        assert s.get(m.Plante, "tomate-1").etat_sante == "malade"
    clock["t"] = T0 + timedelta(minutes=2)
    send(ing, vision_topic("z1", "cam-z1-a"), vision(clock["t"], "tomate/maladie/mildiou"))
    ing.flush()
    assert {a.cible: a for a in actions(sessions)}["camera:cam-z1-a"].resultat == "confirmee"
    assert statut(sessions, d.id) == "terminee"


def test_plant_action_on_an_empty_emplacement_fails():
    ing, sessions, _ = ingestor()
    d = decision(actions=["plante:z9-A1 isolee"])
    send(ing, decision_topic("z1"), d)
    ing.flush()
    assert actions(sessions)[0].resultat == "echec"


def test_proposal_validated_then_executed_keeps_one_action_per_label():
    ing, sessions, clock = ingestor()
    ordre = Ordre(cible="actionneur:ventilo", action="on", duree_s=600)
    p = decision(actions=["proposee:ventilo on 600 s"], statut="proposee", ordres=[ordre],
                 expire=T0 + timedelta(hours=2))  # fmt: skip
    send(ing, decision_topic("z1"), p)
    ing.flush()
    (a,) = actions(sessions)
    assert a.resultat == "proposee" and a.cible == "actionneur:ventilo"
    with sessions() as s:
        assert s.get(m.Decision, p.id).ordres[0]["cible"] == "actionneur:ventilo"
    t1 = T0 + timedelta(minutes=5)
    clock["t"] = t1
    send(ing, decision_topic("z1"), p.model_copy(update=dict(statut="validee")))
    run = p.model_copy(update=dict(statut="executee", actions=["cmd:ventilo on 600 s"]))
    send(ing, decision_topic("z1"), run)
    send(ing, *command(run, t1, duree_s=600))
    send(ing, state_topic("z1", "ventilo"), ActuatorState(ts=t1, action="on"))
    ing.flush()
    (a,) = actions(sessions)
    assert a.resultat == "confirmee" and a.label == "ventilo on 600 s"


def test_proposal_expires_and_its_actions_are_cancelled():
    ing, sessions, clock = ingestor()
    p = decision(actions=["proposee:plante z1-A1 isolee"], statut="proposee",
                 expire=T0 + timedelta(hours=2))  # fmt: skip
    send(ing, decision_topic("z1"), p)
    ing.flush()
    clock["t"] = T0 + timedelta(hours=2, seconds=1)
    send(ing, state_topic("z1", "led"), ActuatorState(ts=clock["t"], action="off"))
    ing.flush()
    assert statut(sessions, p.id) == "expiree"
    assert actions(sessions)[0].resultat == "annulee"
    with sessions() as s:
        assert s.get(m.Plante, "tomate-1").etat_sante == "sain"  # never applied


def test_command_of_a_lost_decision_still_gives_an_action():
    ing, sessions, _ = ingestor()
    lost = decision(9, type_="securite")
    topic, cmd = command(lost, T0, action="off", actuator="chauffage")
    send(ing, topic, cmd.model_copy(update=dict(source="safety")))
    send(ing, state_topic("z1", "chauffage"), ActuatorState(ts=T0, action="off"))
    ing.flush()
    (a,) = actions(sessions)
    assert a.decision_id == lost.id and a.type == "securite" and a.resultat == "confirmee"
    assert a.label == "chauffage off"


def test_tree_groups_and_text():
    ing, sessions, _ = ingestor()
    send(ing, decision_topic("z1"), decision(1, type_="routine", regle="lumiere.photoperiode",
                                             actions=["cmd:led on"]))  # fmt: skip
    exc = decision(2, actions=["cmd:ventilo on 900 s", "alerte", "proposee:plante z1-A1 isolee"])
    send(ing, decision_topic("z1"), exc)
    send(ing, *command(exc, T0, duree_s=900))
    send(ing, state_topic("z1", "ventilo"), ActuatorState(ts=T0, action="on"))
    sec = decision(
        3,
        type_="securite",
        regle="securite.t_max",
        explication="T° 36 °C > 35 °C → chauffage off",
        actions=["bloquee:chauffage on (securite.t_max)"],
    )
    send(ing, decision_topic("z1"), sec)
    ing.flush()
    tree = build_tree(sessions(), T0 - timedelta(hours=1), T0 + timedelta(hours=1), "z1")
    assert tree["label"] == "Serre « Maison »"
    (z1,) = tree["children"]
    assert [g["id"] for g in z1["children"]] == ["z1/routine", "z1/exceptionnelle", "z1/securite"]
    (dec,) = z1["children"][1]["children"]
    assert dec["type"] == "decision" and dec["niveau"] == "1"
    assert dec["resume"] == "HR > 90 % depuis 11 h"
    assert [a["resultat"] for a in dec["children"]] == ["confirmee", "confirmee", "proposee"]
    text = render_text(tree)
    assert "├── Routines" in text and "└── Sécurité" in text
    assert "ventilo on 900 s  ✔" in text and "⏳ proposée" in text and "✖ bloquée" in text
    assert (
        build_tree(sessions(), T0 + timedelta(hours=2), T0 + timedelta(hours=3), "z1")["children"][
            0
        ]["children"]
        == []
    )
