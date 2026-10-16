"""HTTP API (docs/12 §5) for the decisions and the action tree (docs/10): SQLite, in-memory
bus, FastAPI test client."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.ingestion.mqtt_ingest import Ingestor
from common.mqtt import Decision, Ordre, decision_topic, decode, encode
from edge.publisher import LoopbackBus, LoopbackPublisher

from .backend_utils import T0, seeded_db


def proposal(n=1, expire=T0 + timedelta(hours=2)):
    return Decision(
        id=f"dec-20260715-1000-z1-{n:03d}",
        ts=T0,
        zone="z1",
        niveau=1,
        origine="controller",
        regle={"id": "virus.isolement", "version": 1},
        type="exceptionnelle",
        explication="tomate/virus/mosaique sur z1-A1 → isoler la plante",
        actions=["proposee:plante z1-A1 isolee", "alerte"],
        ordres=[Ordre(cible="plante:z1-A1", action="isolee")],
        statut="proposee",
        expire=expire,
    )


@pytest.fixture
def api():
    _, sessions = seeded_db()
    bus = LoopbackBus()
    clock = {"t": T0 + timedelta(minutes=5)}
    ing = Ingestor(sessions, clock=lambda: clock["t"])
    ing.attach(bus)
    for d in (proposal(1), proposal(2), proposal(3, expire=T0 + timedelta(minutes=1))):
        ing.on_message(decision_topic("z1"), encode(d))
    ing.flush()
    app = create_app(sessions, LoopbackPublisher("backend-api", bus), clock=lambda: clock["t"])
    return TestClient(app), bus, ing, sessions


def published(bus):
    return [decode(t, p) for t, p in bus.log if t.endswith("/decision")]


def test_list_and_record(api):
    client, *_ = api
    rows = client.get("/decisions", params={"zone": "z1", "statut": "proposee"}).json()
    assert {r["id"] for r in rows} == {proposal(1).id, proposal(2).id}  # 3 has expired
    assert client.get("/decisions", params={"type": "routine"}).json() == []
    rec = client.get(f"/decisions/{proposal(1).id}").json()
    assert rec["ordres"] == [Ordre(cible="plante:z1-A1", action="isolee").model_dump(mode="json")]
    assert [a["resultat"] for a in rec["actions_detail"]] == ["proposee", "confirmee"]
    assert rec["preuves"]["vision"] == [] and rec["regle"]["id"] == "virus.isolement"
    assert client.get("/decisions/dec-inconnue").status_code == 404


def test_validate_publishes_the_decision_for_the_controller(api):
    client, bus, ing, _ = api
    did = proposal(1).id
    r = client.post(f"/decisions/{did}/valider", json={"utilisateur": "leonard"})
    assert r.status_code == 200 and r.json()["statut"] == "validee"
    (msg,) = published(bus)
    assert msg.id == did and msg.statut == "validee" and msg.ordres == proposal(1).ordres
    assert "validée par ui:leonard" in msg.explication
    assert client.post(f"/decisions/{did}/valider", json={}).status_code == 409  # answered
    ing.flush()
    assert client.get(f"/decisions/{did}").json()["statut"] == "validee"


def test_reject_and_expired(api):
    client, bus, _, _ = api
    did = proposal(2).id
    r = client.post(f"/decisions/{did}/rejeter", json={"commentaire": "fausse alerte"})
    assert r.json()["statut"] == "rejetee" and "fausse alerte" in r.json()["explication"]
    assert published(bus)[0].statut == "rejetee"
    rec = client.get(f"/decisions/{did}").json()
    assert rec["actions_detail"][0]["resultat"] == "annulee"
    r = client.post(f"/decisions/{proposal(3).id}/valider", json={})
    assert r.status_code == 409 and "expiree" in r.json()["detail"]  # marked by reconcile


def test_manual_action(api):
    client, bus, _, _ = api
    body = dict(zone="z1", actionneur="ventilo", action="on", duree_s=600,
                utilisateur="leonard", justification="aérer")  # fmt: skip
    r = client.post("/actions/manuelle", json=body)
    assert r.status_code == 200
    (msg,) = published(bus)
    assert msg.type == "manuelle" and msg.niveau == "manuel" and msg.statut == "validee"
    assert msg.origine == "ui:leonard" and msg.ordres[0].cible == "actionneur:ventilo"
    assert client.get(f"/decisions/{msg.id}").json()["statut"] == "validee"
    bad = dict(body, actionneur="pompe_nutri", duree_s=None)  # a pump must be bounded
    assert client.post("/actions/manuelle", json=bad).status_code == 422
    assert client.post("/actions/manuelle", json=dict(body, zone="z9")).status_code == 404


def test_tree(api):
    client, *_ = api
    tree = client.get("/actions/arbre", params={"zone": "z1"}).json()
    (z1,) = tree["children"]
    (group,) = z1["children"]
    assert group["id"] == "z1/exceptionnelle" and len(group["children"]) == 3


def test_read_only_api():
    _, sessions = seeded_db()
    client = TestClient(create_app(sessions))
    assert client.get("/decisions").status_code == 200
    r = client.post("/actions/manuelle", json=dict(zone="z1", actionneur="led", action="off",
                                                   justification="x"))  # fmt: skip
    assert r.status_code == 503
