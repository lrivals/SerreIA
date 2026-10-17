"""G3 validation on the PC (docs/07): a decision of the simulator (vision + sensors)
consultable with its evidence and its actions, a proposal validated through the API and
run by the controller — simulator, controller, ingestion and API on one in-memory bus."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.db import models as m
from backend.ingestion.mqtt_ingest import Ingestor
from edge.controller.service import Controller
from edge.publisher import LoopbackBus, LoopbackPublisher
from sim.faults import Faults, parse_fault
from sim.simulation import Simulation

from .backend_utils import seeded_db
from .controller_utils import greenhouse

START = datetime(2026, 7, 15, 6, 0, tzinfo=UTC)  # 08:00 Europe/Paris
SCENARIO = ["valeur:z1/humidite=92@0-600", "maladie:z1-A1/tomate/maladie/mildiou@15-600"]


def test_mildew_decision_traced_from_the_simulator_to_the_api():
    _, sessions = seeded_db("sqlite://", START)
    bus = LoopbackBus()
    clock = {"t": START}
    ing = Ingestor(sessions, clock=lambda: clock["t"])
    ing.attach(bus)
    ctl = Controller(greenhouse(), LoopbackPublisher("pi-controller", bus))
    faults = Faults([parse_fault(s, START) for s in SCENARIO])
    sim = Simulation(LoopbackPublisher("sim", bus), START, seed=1, faults=faults, controller=ctl)
    api = create_app(sessions, LoopbackPublisher("backend-api", bus), clock=lambda: clock["t"])
    client = TestClient(api)

    def run(minutes):
        end = sim.t + timedelta(minutes=minutes)
        while sim.t < end:
            sim.step()
            clock["t"] = sim.t
        ing.flush()

    run(80)
    exc = client.get("/api/decisions", params={"zone": "z1", "type": "exceptionnelle"}).json()
    by_rule = {d["regle"]["id"]: d for d in exc}
    assert {"maladie.mildiou.ventilation", "maladie.mildiou.plante"} <= set(by_rule)

    # The record: vision evidence (image, class, confidence, confirmations), sensors, actions.
    rec = client.get(f"/api/decisions/{by_rule['maladie.mildiou.plante']['id']}").json()
    (v,) = rec["preuves"]["vision"]
    assert v["camera"] == "cam-z1-a" and v["emplacement"] == "z1-A1"
    assert v["classe"] == "tomate/maladie/mildiou" and v["confirmations"] == 3
    assert v["image_id"].startswith("cam-z1-a-")
    agregats = {c["agregat"] for c in rec["preuves"]["capteurs"]}
    assert {"duree_au_dessus", "moyenne_12h"} <= agregats
    results = {a["cible"]: a["resultat"] for a in rec["actions_detail"]}
    assert results["plante:z1-A1"] == "confirmee" and results["alerte"] == "confirmee"
    assert rec["statut"] == "terminee"

    vent = client.get(f"/api/decisions/{by_rule['maladie.mildiou.ventilation']['id']}").json()
    (act,) = [a for a in vent["actions_detail"] if a["cible"] == "actionneur:ventilo"]
    assert act["resultat"] == "confirmee" and act["commande"]["source"] == "controller"
    assert vent["commandes"][0]["raison"].startswith(vent["id"])

    # The isolation waits for the user; validated through the API, run by the controller.
    (prop,) = client.get("/api/decisions", params={"statut": "proposee"}).json()
    assert prop["regle"]["id"] == "maladie.mildiou.isolement"
    assert client.post(f"/api/decisions/{prop['id']}/valider", json={}).status_code == 200
    run(1)
    rec = client.get(f"/api/decisions/{prop['id']}").json()
    assert rec["statut"] == "terminee"
    assert [a["resultat"] for a in rec["actions_detail"]] == ["confirmee"]
    with sessions() as s:
        assert s.get(m.Plante, "tomate-1").etat_sante == "isolee"

    # The tree: routines aggregated, the mildew decisions with their actions.
    tree = client.get(
        "/api/actions/arbre",
        params={"zone": "z1", "debut": START.isoformat(), "fin": sim.t.isoformat()},
    ).json()
    groups = {g["id"]: g for g in tree["children"][0]["children"]}
    assert all(r["cycles"] >= 1 for r in groups["z1/routine"]["children"])
    ids = {d["id"] for d in groups["z1/exceptionnelle"]["children"]}
    assert prop["id"] in ids and by_rule["maladie.mildiou.plante"]["id"] in ids
    assert ing.rejets == 0
