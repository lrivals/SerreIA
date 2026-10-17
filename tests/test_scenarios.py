"""System test in simulated scenarios (docs/16): scenario files, forcings, the two scenarios
replayed at full speed and checked against their expected outcome, the frozen history and
the agent on it (scripted LLM, no API call). The two runs take about 1 min 30 s."""

import json
import shutil
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.agent.config import AgentConfig
from backend.agent.eval import load_questions, out_of_limits, score
from backend.agent.fixtures import history_from_scenario
from backend.agent.llm import AgentIndisponible, ScriptedLLM
from backend.agent.loop import Agent
from backend.agent.tools import Tools
from backend.api.app import Settings, create_app
from backend.db import models as m
from backend.db.session import make_engine, make_sessions
from backend.traceability import reconcile
from common.mqtt import (
    ActuatorState,
    Command,
    Decision,
    VisionResult,
    command_raison,
    decode,
    encode,
)
from edge.controller.config import DEFAULT_CONFIG
from edge.controller.service import NODE, build
from edge.publisher import LoopbackBus, LoopbackPublisher
from sim.attendus import Bus, check_entries, invariants, verifier
from sim.faults import Faults, parse_fault
from sim.figer import end_of, figer
from sim.model import ZoneModel, ZoneParams
from sim.scenario import Scenario, parse_offset, parse_time, run_fast
from sim.simulation import Simulation, default_layout
from sim.weather import WeatherState

from .backend_utils import seeded_db
from .controller_utils import greenhouse

T0 = datetime.fromisoformat("2026-07-14T20:00+02:00")


def scenario(**kw) -> Scenario:
    raw = dict(nom="test", debut="2026-07-14T20:00+02:00", duree_h=1) | kw
    return Scenario.parse(raw)


# --- scenario files ----------------------------------------------------------------------


def test_times():
    assert parse_offset("9h") == timedelta(hours=9)
    assert parse_offset("13h40") == timedelta(hours=13, minutes=40)
    assert parse_offset("90min") == parse_offset(90) == timedelta(minutes=90)
    assert parse_time("J1 10:00", T0) == datetime.fromisoformat("2026-07-15T10:00+02:00")
    assert parse_time("2h", T0) == T0 + timedelta(hours=2)
    with pytest.raises(ValueError):
        parse_time("J0 08:00", T0)  # before the start
    with pytest.raises(ValueError):
        parse_offset("demain")


def test_parse_scenario_and_faults():
    sc = scenario(
        pannes=["fige:z1/temperature@30-90", {"panne": "cuve_vide:z2", "de": "J1 00:00"}],
        meteo={"nuages": [{"de": "1h", "a": "2h", "couverture": 0.8}]},
        vision=[{"t": "J1 01:00", "camera": "cam-z1-a", "emplacement": "z1-A1",
                 "classe": "tomate/maladie/mildiou", "conf": 0.7}],
    )  # fmt: skip
    assert sc.pannes[1] == "cuve_vide:z2@240"
    f = sc.faults()
    assert f.tank_empty("z2", T0 + timedelta(hours=4)) and not f.tank_empty("z2", T0)
    assert sc.nuages == [(T0 + timedelta(hours=1), T0 + timedelta(hours=2), 0.8)]
    for bad in (
        dict(forcages=[{"grandeur": "vent", "zone": "z1", "valeur": 1, "de": 0}]),
        dict(forcages=[{"grandeur": "ph", "zone": "z2", "valeur": 7, "derive": 1, "de": 0}]),
        dict(forcages=[{"grandeur": "ph", "zone": "z2", "derive": 1, "de": 0}]),
        dict(forcages=[{"grandeur": "humidite_sol", "zone": "z1", "valeur": 30, "de": 0}]),
        dict(pannes=["fige:z1@nope"]),
    ):
        with pytest.raises(ValueError):
            scenario(**bad)


def test_scenario_files_load():
    for nom in ("journee", "mildiou"):
        sc = Scenario.load(nom)
        assert sc.nom == nom and sc.attendus_path is not None and not sc.cameras


def test_forcings_on_the_zone_model():
    sc = scenario(forcages=[
        {"grandeur": "humidite", "zone": "z1", "valeur": 93, "de": 0, "a": "1h"},
        {"grandeur": "humidite_sol", "zone": "z1", "emplacement": "z1-A1", "valeur": 30,
         "de": "30min"},
        {"grandeur": "ph", "zone": "z2", "derive": 0.4, "de": 0, "a": "1h"},
        {"grandeur": "presence", "zone": "z1", "valeur": 1, "de": 0, "a": "10min"},
    ])  # fmt: skip
    inj = sc.injector(default_layout())
    z1 = ZoneModel("z1", ZoneParams(emplacements=["z1-A1"]))
    z2 = ZoneModel("z2", ZoneParams(hydro=True))
    ph0, dt = z2.ph, 10.0
    t = T0
    for _ in range(360):  # 1 h
        t += timedelta(seconds=dt)
        for zone, model in (("z1", z1), ("z2", z2)):
            inj.force(zone, model, t, dt)
        if t == T0 + timedelta(minutes=5):
            assert z1.presence == 1
        if t == T0 + timedelta(minutes=40):
            assert z1.hr == 93 and z1.soil["z1-A1"] == 30
            z1.soil["z1-A1"] = 50  # set once: not forced again
    assert z1.soil["z1-A1"] == 50
    assert z2.ph == pytest.approx(ph0 + 0.4, abs=0.01)


def test_cloud_override_and_fake_vision():
    sc = scenario(
        meteo={"nuages": [{"de": 0, "a": "1h", "couverture": 1.0}]},
        vision=[{"t": "10min", "camera": "cam-z1-a", "emplacement": "z1-A1",
                 "classe": "tomate/maladie/mildiou", "conf": 0.62}],
    )  # fmt: skip
    layout = default_layout()
    inj = sc.injector(layout)
    assert layout.cameras == []  # camera_service not running
    w = WeatherState(t_ext=20, rayonnement=662.5, hr_ext=70, pression=1013, nuages=0.45)
    dark = inj.weather(T0 + timedelta(minutes=1), w)
    assert dark.nuages == 1.0 and dark.rayonnement == pytest.approx(250.0)
    assert inj.weather(T0 + timedelta(hours=2), w) is w
    assert inj.vision(T0 + timedelta(minutes=5)) == []
    ((topic, r),) = inj.vision(T0 + timedelta(minutes=10))
    assert topic == "serre/z1/vision/cam-z1-a" and isinstance(
        decode(topic, encode(r)), VisionResult
    )
    (d,) = r.detections
    x, y, w_, h = d.bbox
    assert x + w_ <= 0.5 and d.classe_conf == 0.62 and d.sante == "anormal"  # inside z1-A1
    assert inj.vision(T0 + timedelta(hours=1)) == []  # once


# --- checks ------------------------------------------------------------------------------


def _decision(id_, ts, regle, statut="executee", zone="z2"):
    return Decision(id=id_, ts=ts, zone=zone, niveau=0, origine="controller",
                    regle={"id": regle, "version": 1}, type="securite", config_version=1,
                    explication="x", statut=statut)  # fmt: skip


def test_invariants_catch_untraced_and_unbounded_commands():
    ts = T0
    pump = Command(ts=ts, action="on", source="controller", raison="hors décision")
    refus = "bloquee_securite"
    blocked = [_decision(i, ts, "hydro.circulation", refus) for i in ("dec-1", "dec-2")]
    log = [
        *[("serre/z2/decision", encode(d)) for d in blocked],
        ("serre/z2/cmd/pompe_nutri", encode(pump.model_copy(update={"duree_s": 5000.0}))),
        ("serre/z1/cmd/ventilo", encode(Command(ts=ts, action="pwm", valeur=100, source="c",
                                                raison=command_raison("dec-1", "x")))),
        ("serre/z1/cmd/ventilo", encode(Command(ts=ts + timedelta(seconds=60), action="off",
                                                source="c", raison=command_raison("dec-1", "x")))),
        ("serre/z1/etat/ventilo", b"pas du json"),
    ]  # fmt: skip
    errors = invariants(Bus.of(log), greenhouse())
    text = "\n".join(errors)
    assert "message invalide" in text and "sans décision" in text
    assert "5000 s > 1800 s" in text and "refus répété" in text and "marche_min_s" in text


def test_expected_entries_and_known_gaps():
    log = [("serre/z1/decision", encode(_decision("dec-1", T0 + timedelta(hours=1), "a.b",
                                                  zone="z1")))]  # fmt: skip
    bus, fin = Bus.of(log), T0 + timedelta(hours=2)
    res = check_entries({"attendus": [{"nom": "a", "regle": "a.b", "de": "30min", "a": "2h"}],
                         "interdits": [{"nom": "b", "regle": "a.b", "connu": "bug"}]},
                        bus, T0, fin)  # fmt: skip
    assert res.ok and res.connus and not res.resolus
    res = check_entries({"attendus": [{"nom": "a", "regle": "a.b", "a": "30min"},
                                      {"nom": "c", "regle": "x", "connu": "corrigé ?", "max": 0}]},
                        bus, T0, fin)  # fmt: skip
    assert not res.ok and "« a »" in res.ecarts[0] and res.resolus


# --- scenario 1 --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def journee():
    sc = Scenario.load("journee")
    _, sessions = seeded_db("sqlite://", sc.debut)
    return run_fast(sc, sessions)


def test_journee_meets_its_expected_outcome(journee):
    res = verifier(journee)
    assert res.ok, "\n".join(res.ecarts)
    assert not res.connus and not res.resolus
    day = journee.consommation["2026-07-15"]
    assert day["kwh"] > 0 and day["litres"] > 0 and day["cout"] > 0 and day["dli"]["z1"] > 0


def test_journee_decisions_are_traced_in_the_database(journee):
    with journee.sessions() as s:
        assert s.scalars(select(m.Decision).where(
            m.Decision.regle_id == "securite.cuve_vide")).first() is not None  # fmt: skip
        ids = set(s.scalars(select(m.Decision.id)))
        cmds = set(s.scalars(select(m.Commande.decision_id)))
        assert cmds and cmds <= ids


# --- scenario 2: frozen history ----------------------------------------------------------


@pytest.fixture(scope="module")
def historique(tmp_path_factory):
    out = tmp_path_factory.mktemp("mildiou")
    run, res = figer(Scenario.load("mildiou"), out)
    return out, run, res


def test_mildiou_meets_its_expected_outcome(historique):
    out, run, res = historique
    assert res.ok, "\n".join(res.ecarts)
    assert not res.resolus, res.resolus  # a known gap fixed: update mildiou.attendus.yaml
    meta = json.loads((out / "scenario.json").read_text())
    assert meta["nom"] == "mildiou" and meta["ok"] and end_of(out) < run.sim.t
    assert "vérification : OK" in (out / "verification.txt").read_text()


def test_frozen_demo_for_the_game_view(historique):
    out, run, _ = historique
    demo = json.loads((out / "serre-demo.json").read_text())
    d = demo["donnees"]
    assert d["serre"] and [z["id"] for z in d["zones"]] == ["z1", "z2"]
    assert set(d["tableaux"]) == {"z1", "z2"} and len(d["plans"]) == 2
    assert d["actionneurs"] and d["capteurs"] and d["noeuds"]
    assert demo["conso"]["totaux"]["kwh"] > 0  # the last day, not an empty one
    t = [e["t"] for e in demo["evenements"]]
    assert t == sorted(t) and 0 <= t[0] and t[-1] <= 241
    kinds = {e["evenement"]["kind"] for e in demo["evenements"]}
    assert {"etat", "decision", "alerte", "vision"} <= kinds and "capteur" not in kinds


@pytest.fixture
def hist(historique, tmp_path):
    """A private copy of the frozen history: (sessions, History, bus, tools)."""
    out, *_ = historique
    shutil.copy(out / "serre.db", tmp_path / "serre.db")
    sessions = make_sessions(make_engine(f"sqlite:///{tmp_path / 'serre.db'}"))
    h = history_from_scenario(sessions, end_of(out))
    bus = LoopbackBus()
    tools = Tools(sessions, LoopbackPublisher("backend-api", bus), AgentConfig(), lambda: h.now)
    return sessions, h, bus, tools


def agent_decisions(sessions) -> list[m.Decision]:
    with sessions() as s:
        return list(s.scalars(select(m.Decision).where(m.Decision.niveau == "agent")))


def test_history_identifiers(hist):
    sessions, h, *_ = hist
    assert h.mildiou.startswith("dec-20260722-0200") and len(h.images) == 3
    assert h.images == sorted(h.images) and all(i.startswith("cam-z1-a-") for i in h.images)
    assert h.isolement != h.mildiou and h.arrosages and float(h.humectation.replace(",", ".")) > 0


def _scripted(q: dict, h, sessions) -> list:
    """Tool calls and a final answer for a reference question (docs/16 §4)."""
    t = h.now.isoformat()
    with sessions() as s:
        ts = s.get(m.Decision, h.mildiou).ts.replace(tzinfo=UTC)
    night = {
        "zone": "z1",
        "debut": (ts - timedelta(minutes=30)).isoformat(),
        "fin": (ts + timedelta(hours=1)).isoformat(),
    }  # "cette nuit vers 2 h 30"
    steps = {
        "pourquoi-ventilation": [
            [("tool", "get_decisions", night)],
            [f"Règle maladie.mildiou.ventilation, décision {h.mildiou}, image {h.images[-1]} "
             f"(3 captures), HR > 90 % depuis {h.humectation} h."],
        ],
        "que-faire-a1": [
            [("tool", "get_plante", {"emplacement": "z1-A1"}),
             ("tool", "get_vision", {"emplacement": "z1-A1"}),
             ("tool", "get_mesures", {"zone": "z1", "types": ["humidite", "temperature"]})],
            [("tool", "proposer_consigne", dict(
                recette_id="tomate-standard", stade="floraison", grandeur="humidite",
                plage=[50, 60], duree_h=72, justification="mildiou confirmé sur A1",
                preuves_refs=[h.mildiou])),
             ("tool", "proposer_etat_plante", dict(
                plante_id="tomate-1", etat_sante="isolee", justification="mildiou",
                preuves_refs=h.images))],
            ["Mildiou sur A1 : HR max 60 % pendant 72 h, plante isolée ; retirer les feuilles "
             "atteintes est manuel."],
        ],
        "led-2h": [
            [("tool", "get_consommation", {"zone": "z1"}),
             ("tool", "get_mesures", {"zone": "z1", "types": ["lux"]})],
            [("tool", "proposer_action", dict(
                zone="z1", actionneur="led", action="pwm", valeur=100, duree_s=7200,
                justification="DLI du jour bas", preuves_refs=[
                    f"mesure:z1/lux/{(h.now - timedelta(hours=8)).isoformat()}/{t}"]))],
            ["Je propose LED à 100 % pendant 2 h, à valider."],
        ],
        "eau-semaine": [
            [("tool", "get_consommation", {"periode": "semaine"})],
            [f"{h.litres} L cette semaine (arrosage et circulation NFT)."],
        ],
    }  # fmt: skip
    return steps[q["id"]]


@pytest.mark.parametrize("qid", ["pourquoi-ventilation", "que-faire-a1", "led-2h",
                                 "eau-semaine"])  # fmt: skip
def test_reference_dialogues_on_the_simulated_history(hist, qid):
    sessions, h, bus, _ = hist
    q = next(q for q in load_questions() if q["id"] == qid)
    llm = ScriptedLLM(_scripted(q, h, sessions))
    agent = Agent(sessions, llm, LoopbackPublisher("backend-api", bus), clock=lambda: h.now)
    events = list(agent.chat(q["question"]))
    assert not [e for e in events if e["type"] == "outil" and e["erreur"]], events
    result = score(q, events, sessions, h)
    assert result["ok"], result
    if qid == "pourquoi-ventilation":  # the evidence comes from the tools, not invented
        sent = json.dumps(llm.calls[-1]["messages"], ensure_ascii=False)
        assert h.mildiou in sent and h.images[-1] in sent


@pytest.mark.parametrize(
    "outil, args, motif",
    [
        ("proposer_action", dict(zone="z1", actionneur="pompe_nutri", action="on",
                                 duree_s=600), "duree_max"),
        ("proposer_action", dict(zone="z2", actionneur="brumisateur", action="on",
                                 duree_s=60), "actionneur_inconnu"),
        ("proposer_consigne", dict(recette_id="tomate-standard", stade="floraison",
                                   grandeur="temperature.jour", plage=[30, 40]), "hors limites"),
    ],
)  # fmt: skip
def test_guardrails_create_nothing(hist, outil, args, motif):
    sessions, h, bus, tools = hist
    r = tools.run(outil, args | dict(justification="demande", preuves_refs=[h.mildiou]))
    assert r.error and motif in json.dumps(r.content, ensure_ascii=False)
    assert agent_decisions(sessions) == [] and out_of_limits(sessions) == []
    assert not [t for t, _ in bus.log if t.endswith("/decision") or "/cmd/" in t]


def test_unvalidated_proposal_expires(hist):
    sessions, h, _, tools = hist
    led = dict(zone="z1", actionneur="led", action="pwm", valeur=100, duree_s=7200,
               justification="DLI bas", preuves_refs=[h.mildiou])  # fmt: skip
    did = tools.run("proposer_action", led).proposition["id"]
    with sessions.begin() as s:
        reconcile(s, h.now + timedelta(hours=2, minutes=1))
        assert s.get(m.Decision, did).statut == "expiree"


def test_greenhouse_unaffected_when_the_llm_is_unavailable(hist):
    sessions, h, *_ = hist
    with sessions() as s:
        before = s.scalars(select(m.Decision.id)).all()
    agent = Agent(sessions, ScriptedLLM([AgentIndisponible("clé API refusée (401)")]),
                  clock=lambda: h.now)  # fmt: skip
    events = list(agent.chat("Pourquoi la ventilation a tourné ?"))
    assert events[-1]["type"] == "erreur" and "indisponible" in events[-1]["message"]
    with sessions() as s:
        assert s.scalars(select(m.Decision.id)).all() == before


def test_validated_proposals_go_through_the_controller(hist):
    """Validation in the UI → decision then command on the bus, run by the controller
    after safety.py; a pump validated while the tank is empty is refused and traced."""
    sessions, h, _, _ = hist
    bus = LoopbackBus()
    start = datetime(2026, 7, 23, 13, 0, tzinfo=UTC)
    controller = build(DEFAULT_CONFIG, LoopbackPublisher(NODE, bus))
    empty = Faults([parse_fault("cuve_vide:z2@0", start)])
    sim = Simulation(LoopbackPublisher("sim", bus), start, 2, empty, controller=controller)
    sim.run(600)  # the controller sees the greenhouse, the empty tank
    tools = Tools(sessions, LoopbackPublisher("backend-api", bus), AgentConfig(), lambda: sim.t)
    led = tools.run("proposer_action", dict(
        zone="z1", actionneur="led", action="pwm", valeur=100, duree_s=600,
        justification="DLI bas", preuves_refs=[h.mildiou])).proposition["id"]  # fmt: skip
    pompe = tools.run("proposer_action", dict(
        zone="z2", actionneur="pompe_nutri", action="on", duree_s=600,
        justification="circulation", preuves_refs=[h.mildiou])).proposition["id"]  # fmt: skip
    api = create_app(sessions, LoopbackPublisher("backend-api", bus), clock=lambda: sim.t,
                     settings=Settings(frontend=None))  # fmt: skip
    n = len(bus.log)
    with TestClient(api) as client:
        for did in (led, pompe):
            r = client.post(f"/api/decisions/{did}/valider", json={"utilisateur": "test"})
            assert r.status_code == 200, r.text
    sim.run(120)
    after = Bus.of(bus.log[n:])
    seen = {(d.id, d.statut) for d in after.decisions}
    assert (led, "validee") in seen and (led, "executee") in seen
    assert (pompe, "bloquee_securite") in seen
    assert [c for z, a, c in after.commands_of(led) if a == "led" and c.action == "pwm"]
    assert not [c for z, a, c in after.commands if (z, a) == ("z2", "pompe_nutri")
                and c.action == "on"]  # fmt: skip
    states = [decode(t, p) for t, p in bus.log[n:] if t == "serre/z1/etat/led"]
    assert any(isinstance(s, ActuatorState) and s.action == "pwm" for s in states)
    assert sum(1 for d in after.decisions if d.id == pompe and d.statut == "bloquee_securite") == 1
    assert out_of_limits(sessions) == []
