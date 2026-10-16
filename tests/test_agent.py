"""Conversational agent (docs/11): tools, guardrails, proposal life cycle, loop and SSE API,
on the reference history (backend/agent/fixtures.py) with a scripted LLM — no API call."""

import json
import re
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.agent import consignes
from backend.agent.config import AgentConfig
from backend.agent.eval import load_questions, score
from backend.agent.fixtures import IMAGES, MILDIOU_ID, history_db
from backend.agent.llm import AgentIndisponible, ScriptedLLM
from backend.agent.loop import Agent
from backend.agent.prompts import system_blocks
from backend.agent.tools import SPECS, Tools, definitions, load_catalogue
from backend.api.app import create_app
from backend.db import models as m
from backend.traceability import reconcile
from common.mqtt import decode
from edge.publisher import LoopbackBus, LoopbackPublisher

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def frozen():
    """One reference history for the read-only tests."""
    return history_db()


@pytest.fixture
def env():
    sessions, h = history_db()
    bus = LoopbackBus()
    clock = {"t": h.now}
    pub = LoopbackPublisher("backend-api", bus)
    tools = Tools(sessions, pub, AgentConfig(), lambda: clock["t"])
    return sessions, h, bus, clock, tools


def decisions_agent(sessions) -> list[m.Decision]:
    with sessions.begin() as s:
        return list(s.scalars(select(m.Decision).where(m.Decision.niveau == "agent")))


def published(bus):
    return [decode(t, p) for t, p in bus.log if t.endswith("/decision")]


# --- definitions, prompt, catalogue ------------------------------------------------------


def test_definitions_are_stable_and_complete():
    names = [d["name"] for d in definitions()]
    assert names == [s.name for s in SPECS] and len(set(names)) == 12
    assert json.dumps(definitions()) == json.dumps(definitions())  # prompt cache
    for d in definitions():
        assert d["input_schema"]["type"] == "object" and "title" not in d["input_schema"]
        assert d["input_schema"].get("additionalProperties") is False


def test_system_prompt_is_deterministic(frozen):
    sessions, _ = frozen
    with sessions.begin() as s:
        a, b = system_blocks(s), system_blocks(s)
    assert a == b and a[-1]["cache_control"] == {"type": "ephemeral"}
    text = "".join(x["text"] for x in a)
    assert "maladie.mildiou.ventilation" in text and "arrosage-z1" in text
    assert "français" in text and "2026" not in text.split("Description")[0]


def test_catalogue_covers_the_rule_ids_of_the_controller():
    catalogue = load_catalogue()
    pattern = re.compile(
        r'"((?:securite|climat|lumiere|sol|hydro|presence|maladie|nuisible|virus|vision|'
        r'croissance|prevision)\.[a-z_]+(?:\.[a-z_]+)*)"'
    )
    found = set()
    for path in (ROOT / "edge/controller").glob("*.py"):
        found |= set(pattern.findall(path.read_text()))
    assert found and found <= set(catalogue), sorted(found - set(catalogue))
    for entry in catalogue.values():
        assert entry["version"] >= 1 and entry["description"]


# --- reading -----------------------------------------------------------------------------


def test_get_decisions_gives_the_mildew_decision_with_its_evidence(frozen):
    sessions, h = frozen
    t = Tools(sessions, None, AgentConfig(), lambda: h.now)
    r = t.run(
        "get_decisions", {"zone": "z1", "debut": "2026-10-12T02:00", "fin": "2026-10-12T03:00"}
    )
    assert not r.error
    (d,) = [x for x in r.content["decisions"] if x["regle"]["id"] == "maladie.mildiou.ventilation"]
    assert d["id"] == MILDIOU_ID and d["ts"] == "2026-10-12T02:30:00+02:00"
    assert d["preuves"]["vision"][0]["image_id"] == IMAGES[-1]
    assert d["preuves"]["capteurs"][0]["valeur"] == 11.0
    assert [a["label"] for a in d["actions_detail"]] == ["ventilo on 900 s", "alerte"]
    one = t.run("get_decisions", {"decision_id": MILDIOU_ID})
    assert one.content["id"] == MILDIOU_ID and one.content["commandes"][0]["duree_s"] == 900
    assert t.run("get_decisions", {"decision_id": "dec-x"}).error


def test_get_mesures_aggregates_and_downsamples(frozen):
    sessions, h = frozen
    t = Tools(sessions, None, AgentConfig(max_points=50), lambda: h.now)
    r = t.run("get_mesures", {"zone": "z1", "types": ["humidite"], "agregat": "moy_1h"})
    (serie,) = r.content["series"]
    assert serie["n_mesures"] == 144 and len(serie["points"]) == 24
    assert serie["min"] == 70.0 and serie["max"] == 92.0
    assert serie["ref"].startswith("mesure:z1/humidite/2026-10-12T15:00:00+02:00/")
    raw = t.run("get_mesures", {"zone": "z1", "types": ["lux"], "agregat": "brut",
                                "debut": "2026-10-10T15:00"})  # fmt: skip
    assert raw.content["series"][0]["n_mesures"] == 432
    assert len(raw.content["series"][0]["points"]) <= 50
    assert t.run("get_mesures", {"zone": "z9", "types": ["lux"]}).error
    bad = t.run("get_mesures", {"zone": "z1", "types": ["pluie"]})
    assert bad.error and bad.content["erreur"] == "arguments invalides"


def test_get_plante_vision_consommation_regle(frozen):
    sessions, h = frozen
    t = Tools(sessions, None, AgentConfig(), lambda: h.now)
    p = t.run("get_plante", {"emplacement": "z1-A1"}).content
    assert p["plante"]["id"] == "tomate-1" and p["consignes_stade"]["humidite"] == [55, 70]
    assert p["dernieres_classifications"][0]["image_id"] == IMAGES[-1]
    assert t.run("get_plante", {"plante_id": "tomate-1"}).content["emplacement"] == "z1-A1"
    assert t.run("get_plante", {}).error  # one of emplacement / plante_id
    v = t.run("get_vision", {"emplacement": "z1-A1"}).content["resultats"]
    assert [x["classe_conf"] for x in v] == [0.81, 0.74, 0.62]
    c = t.run("get_consommation", {"periode": "semaine", "zone": "z1"}).content
    assert c["totaux"]["litres"] == 4.5 and c["actionneurs"]["arrosage-z1"]["litres"] == 4.5
    assert any(x["jour"] == "2026-10-13" or str(x["jour"]) == "2026-10-13" for x in c["lumiere"])
    g = t.run("get_regle", {"regle_id": "maladie.mildiou.ventilation"}).content
    assert g["valeurs"]["risque.hr_humectation"] == 90 and g["valeurs"]["regles.confirmations"] == 3
    assert g["derniere_decision"] == MILDIOU_ID
    assert t.run("get_regle", {"regle_id": "climat.pluie"}).error


# --- guardrails --------------------------------------------------------------------------


def action(**kw):
    base = dict(zone="z1", actionneur="led", action="pwm", valeur=100, duree_s=7200,
                justification="DLI 11 pour une cible de 25", preuves_refs=[MILDIOU_ID])  # fmt: skip
    return base | kw


@pytest.mark.parametrize(
    "args, motif",
    [
        (action(actionneur="pompe_nutri", action="on", valeur=None, duree_s=600), "duree_max"),
        (action(actionneur="pompe_nutri", action="on", valeur=None, duree_s=None), "duree_s"),
        (action(zone="z2", actionneur="brumisateur", action="on", valeur=None, duree_s=60),
         "actionneur_inconnu"),
        (action(actionneur="chauffage", action="pwm", valeur=50, duree_s=600), "on/off"),
        (action(duree_s=24 * 3600), "duree_max"),
        (action(preuves_refs=["dec-inventee"]), "introuvables"),
        (action(preuves_refs=["mesure:z1/humidite/2020-01-01T00:00/2020-01-02T00:00"]),
         "introuvables"),
        (action(preuves_refs=[]), "arguments invalides"),
        (action(justification=""), "arguments invalides"),
        (action(zone="z7"), "zone inconnue"),
    ],
)  # fmt: skip
def test_proposer_action_refusals_create_nothing(env, args, motif):
    sessions, _, bus, _, tools = env
    r = tools.run("proposer_action", args)
    assert r.error and motif in json.dumps(r.content, ensure_ascii=False)
    assert decisions_agent(sessions) == [] and published(bus) == []


@pytest.mark.parametrize(
    "args, motif",
    [
        (dict(grandeur="temperature.jour", plage=[30, 40]), "hors limites"),
        (dict(grandeur="ph", plage=[3.5, 6.0], recette_id="laitue-hydro", stade="croissance"),
         "hors limites"),
        (dict(grandeur="humidite", plage=[70, 60]), "plage [min, max]"),
        (dict(grandeur="photoperiode_h", plage=[10, 12]), "une seule valeur"),
        (dict(stade="semence"), "absent"),
        (dict(recette_id="cactus"), "recette inconnue"),
    ],
)  # fmt: skip
def test_proposer_consigne_refusals(env, args, motif):
    sessions, *_, tools = env
    base = dict(recette_id="tomate-standard", stade="floraison", grandeur="humidite",
                plage=[50, 60], duree_h=72, justification="mildiou",
                preuves_refs=[MILDIOU_ID])  # fmt: skip
    r = tools.run("proposer_consigne", base | args)
    assert r.error and motif in r.content["erreur"]
    assert decisions_agent(sessions) == []


# --- proposals and their life cycle ------------------------------------------------------


def test_proposer_action_creates_a_pending_decision(env):
    sessions, h, bus, clock, tools = env
    ref = f"mesure:z1/lux/{(h.now - timedelta(hours=8)).isoformat()}/{h.now.isoformat()}"
    r = tools.run("proposer_action", action(preuves_refs=[ref, IMAGES[-1]]), "conv-1")
    assert not r.error, r.content
    card = r.proposition
    assert card["statut"] == "proposee" and card["niveau"] == "agent"
    assert card["ordres"] == [
        dict(
            cible="actionneur:led",
            action="pwm",
            valeur=100.0,
            duree_s=7200.0,
            texte="DLI 11 pour une cible de 25",
        )
    ]
    assert card["estimation"] == {"kwh": 0.48}
    assert card["preuves"]["capteurs"][0]["topic"] == "serre/z1/capteur/lux"
    assert card["preuves"]["vision"][0]["image_id"] == IMAGES[-1]
    assert [a["resultat"] for a in card["actions_detail"]] == ["proposee"]
    assert published(bus) == []  # nothing published before the validation
    (d,) = decisions_agent(sessions)
    assert d.regle_id == "agent.action" and d.type == "manuelle"
    assert (d.expire.replace(tzinfo=None) - d.ts.replace(tzinfo=None)) == timedelta(hours=2)
    with sessions.begin() as s:
        p = s.get(m.AgentProposition, d.id)
        assert p.conversation_id == "conv-1" and p.preuves_refs == [ref, IMAGES[-1]]


def test_unvalidated_proposal_expires(env):
    sessions, h, bus, clock, tools = env
    did = tools.run("proposer_action", action()).proposition["id"]
    with sessions.begin() as s:
        reconcile(s, h.now + timedelta(hours=2, minutes=1))
        assert s.get(m.Decision, did).statut == "expiree"
        assert {
            a.resultat for a in s.scalars(select(m.Action).where(m.Action.decision_id == did))
        } == {"annulee"}


def test_validation_through_the_api(env):
    sessions, h, bus, clock, tools = env
    did = tools.run("proposer_action", action()).proposition["id"]
    client = TestClient(
        create_app(sessions, LoopbackPublisher("api", bus), clock=lambda: clock["t"])
    )
    r = client.post(f"/api/decisions/{did}/valider", json={"utilisateur": "leonard"})
    assert r.status_code == 200 and r.json()["statut"] == "validee"
    (msg,) = published(bus)
    assert msg.id == did and msg.niveau == "agent" and msg.ordres[0].cible == "actionneur:led"


def test_proposer_etat_plante_and_capture(env):
    sessions, h, bus, clock, tools = env
    r = tools.run(
        "proposer_etat_plante",
        dict(
            plante_id="tomate-1", etat_sante="malade", justification="mildiou", preuves_refs=IMAGES
        ),
    )
    assert not r.error and r.proposition["ordres"][0]["cible"] == "plante:z1-A1"
    assert r.proposition["emplacements"] == ["z1-A1"]
    assert tools.run(
        "proposer_etat_plante",
        dict(plante_id="tomate-1", etat_sante="sain", justification="x", preuves_refs=IMAGES),
    ).error
    c = tools.run("demander_capture", dict(camera="cam-z1-a", justification="vérifier A1"))
    assert not c.error and c.proposition is None
    (msg,) = published(bus)  # the only action run without validation
    assert msg.statut == "validee" and msg.ordres[0].cible == "camera:cam-z1-a"
    assert tools.run("demander_capture", dict(camera="cam-z9", justification="x")).error
    offline = Tools(sessions, None, AgentConfig(), lambda: h.now)
    assert offline.run("demander_capture", dict(camera="cam-z1-a", justification="x")).error


def test_consigne_applied_on_validation_then_restored(env):
    sessions, h, bus, clock, tools = env
    r = tools.run("proposer_consigne", dict(recette_id="tomate-standard", stade="floraison",
                                            grandeur="humidite", plage=[50, 60], duree_h=72,
                                            justification="mildiou en A1",
                                            preuves_refs=[MILDIOU_ID]))  # fmt: skip
    assert not r.error, r.content
    card = r.proposition
    assert card["zone"] == "z1" and card["consigne"]["actuelle"] == [55, 70]
    assert card["actions_detail"][0]["resultat"] == "proposee"
    did = card["id"]
    client = TestClient(
        create_app(sessions, LoopbackPublisher("api", bus), clock=lambda: clock["t"])
    )
    assert client.post(f"/api/decisions/{did}/valider", json={}).status_code == 200
    with sessions.begin() as s:
        assert s.get(m.Recette, "tomate-standard").stades["floraison"]["humidite"] == [50, 60]
        version = s.scalars(select(m.Serre)).first().config_version
        assert version > 1 and s.get(m.ConfigExport, version) is not None
        d = s.get(m.Decision, did)
        assert d.actions == ["consigne tomate-standard/floraison humidite [50, 60] 72 h"]
        assert [
            a.resultat for a in s.scalars(select(m.Action).where(m.Action.decision_id == did))
        ] == ["confirmee"]
    (msg,) = published(bus)
    assert msg.statut == "validee" and msg.ordres == []
    with sessions.begin() as s:
        assert consignes.restore_expired(s, h.now + timedelta(hours=71)) == []
        assert consignes.restore_expired(s, h.now + timedelta(hours=72)) == [did]
        assert s.get(m.Recette, "tomate-standard").stades["floraison"]["humidite"] == [55, 70]
        assert s.scalars(select(m.Serre)).first().config_version > version


# --- loop --------------------------------------------------------------------------------


def run(agent, message, conversation_id=None):
    return list(agent.chat(message, conversation_id))


def test_loop_explains_with_tools_and_logs_everything(env):
    sessions, h, bus, clock, _ = env
    llm = ScriptedLLM([
        ["Je regarde le journal.", ("tool", "get_decisions",
                                    {"zone": "z1", "debut": "2026-10-12T02:00",
                                     "fin": "2026-10-12T03:00"})],
        [f"C'est la règle maladie.mildiou.ventilation ({MILDIOU_ID}), image {IMAGES[-1]}."],
    ])  # fmt: skip
    agent = Agent(sessions, llm, LoopbackPublisher("api", bus), clock=lambda: clock["t"])
    events = run(agent, "Pourquoi la ventilation a tourné cette nuit ?")
    kinds = [e["type"] for e in events]
    assert kinds == ["conversation", "texte", "outil", "texte", "fin"]
    assert events[2]["nom"] == "get_decisions" and not events[2]["erreur"]
    assert events[-1]["tokens"]["entree"] == 2000
    # The tool result goes back in one user message, after the assistant tool_use.
    sent = llm.calls[1]["messages"]
    assert [x["role"] for x in sent] == ["user", "assistant", "user"]
    assert sent[0]["content"].startswith("[2026-10-13T15:00+02:00] Pourquoi")
    (res,) = sent[2]["content"]
    assert res["type"] == "tool_result" and MILDIOU_ID in res["content"]
    cid = events[0]["id"]
    with sessions.begin() as s:
        types = list(s.scalars(select(m.AgentJournal.type).where(
            m.AgentJournal.conversation_id == cid).order_by(m.AgentJournal.id)))  # fmt: skip
        assert types == ["utilisateur", "assistant", "appel_outil", "resultat_outil", "assistant"]
        assert len(s.get(m.AgentConversation, cid).messages) == 4
    # The conversation continues with its history.
    llm.steps.append(["Rien d'autre cette nuit."])
    again = run(agent, "Et à part ça ?", cid)
    assert again[0] == {"type": "conversation", "id": cid}
    assert len(llm.calls[-1]["messages"]) == 5


def test_loop_refused_proposal_then_rephrased(env):
    sessions, h, bus, clock, _ = env
    llm = ScriptedLLM([
        [("tool", "proposer_action", action(actionneur="pompe_nutri", action="on", valeur=None,
                                            duree_s=600))],
        [("tool", "proposer_action", action(actionneur="pompe_nutri", action="on", valeur=None,
                                            duree_s=120))],
        ["La pompe est limitée à 120 s : je propose 2 min."],
    ])  # fmt: skip
    agent = Agent(sessions, llm, clock=lambda: clock["t"])
    events = run(agent, "Lance la pompe 10 min")
    outils = [e for e in events if e["type"] == "outil"]
    assert [o["erreur"] for o in outils] == [True, False]
    (prop,) = [e for e in events if e["type"] == "proposition"]
    assert prop["decision"]["ordres"][0]["duree_s"] == 120
    refused = llm.calls[1]["messages"][-1]["content"][0]
    assert refused["is_error"] and "duree_max" in refused["content"]
    (d,) = decisions_agent(sessions)
    assert d.id == prop["decision"]["id"]


def test_loop_degrades_when_the_llm_is_unavailable(env):
    sessions, h, bus, clock, _ = env
    agent = Agent(sessions, ScriptedLLM([AgentIndisponible("API injoignable (réseau)")]),
                  clock=lambda: clock["t"])  # fmt: skip
    events = run(agent, "Bonjour")
    assert events[-1] == {
        "type": "erreur",
        "message": "agent indisponible : API injoignable (réseau)",
    }
    with sessions.begin() as s:
        assert s.scalar(select(func.count()).select_from(m.AgentJournal).where(
            m.AgentJournal.type == "erreur")) == 1  # fmt: skip


def test_loop_budget(env):
    sessions, h, bus, clock, _ = env
    cfg = AgentConfig(tokens_conversation=1000)
    llm = ScriptedLLM([[("tool", "get_serre", {})], ["ok"]])
    events = run(Agent(sessions, llm, cfg=cfg, clock=lambda: clock["t"]), "Décris la serre")
    assert events[-1]["type"] == "erreur" and "budget" in events[-1]["message"]
    assert len(llm.calls) == 1  # refused before the second call
    day = AgentConfig(tokens_jour=500)
    events = run(Agent(sessions, ScriptedLLM([["ok"]]), cfg=day, clock=lambda: clock["t"]), "x")
    assert "journalier" in events[-1]["message"]


def test_loop_tool_limit(env):
    sessions, h, bus, clock, _ = env
    llm = ScriptedLLM([[("tool", "get_serre", {})]] * 3)
    cfg = AgentConfig(max_tours=3)
    events = run(Agent(sessions, llm, cfg=cfg, clock=lambda: clock["t"]), "x")
    assert events[-1]["type"] == "erreur" and "trop d'appels" in events[-1]["message"]


# --- API ---------------------------------------------------------------------------------


def sse_events(text: str) -> list[dict]:
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def test_api_chat_sse_and_conversations(env):
    sessions, h, bus, clock, _ = env
    llm = ScriptedLLM([
        [("tool", "proposer_action", action())],
        ["Proposition : LED z1 à 100 % pendant 2 h."],
    ])  # fmt: skip
    pub = LoopbackPublisher("api", bus)
    agent = Agent(sessions, llm, pub, clock=lambda: clock["t"])
    client = TestClient(create_app(sessions, pub, clock=lambda: clock["t"], agent=agent))
    r = client.post("/api/agent/chat", json={"message": "Allume les LED à fond pendant 2 h"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    assert "event: proposition" in r.text
    events = sse_events(r.text)
    cid = events[0]["id"]
    did = next(e["decision"]["id"] for e in events if e["type"] == "proposition")
    (conv,) = client.get("/api/agent/conversations").json()
    assert conv["id"] == cid and conv["tokens"] == 2200
    detail = client.get(f"/api/agent/conversations/{cid}").json()
    assert detail["propositions"][0]["decision_id"] == did
    assert detail["propositions"][0]["statut"] == "proposee"
    assert [j["type"] for j in detail["journal"]][0] == "utilisateur"
    assert client.get("/api/agent/conversations/conv-x").status_code == 404
    # Validated in the UI like any proposal.
    assert client.post(f"/api/decisions/{did}/valider", json={}).status_code == 200
    assert published(bus)[0].id == did


def test_api_without_agent(env):
    sessions, *_ = env
    client = TestClient(create_app(sessions))
    assert client.post("/api/agent/chat", json={"message": "x"}).status_code == 503
    assert client.get("/api/agent/statut").json() == {"disponible": False, "modele": None}
    assert client.get("/api/agent/conversations").json() == []
    assert client.get("/api/decisions").status_code == 200  # the rest works the same


# --- evaluation ------------------------------------------------------------------------


def test_reference_questions_and_scoring(env):
    questions = load_questions()
    assert len(questions) >= 10 and len({q["id"] for q in questions}) == len(questions)
    sessions, h, bus, clock, _ = env
    q = next(q for q in questions if q["id"] == "pourquoi-ventilation")
    llm = ScriptedLLM([
        [("tool", "get_decisions", {"zone": "z1", "debut": "2026-10-12T02:00",
                                    "fin": "2026-10-12T03:00"})],
        [f"Règle maladie.mildiou.ventilation, décision {MILDIOU_ID}, image {IMAGES[-1]}, "
         "HR > 90 % depuis 11 h."],
    ])  # fmt: skip
    agent = Agent(sessions, llm, clock=lambda: clock["t"])
    result = score(q, list(agent.chat(q["question"])), sessions, h)
    assert result["ok"], result
    bad = score(q, [{"type": "texte", "texte": "Je ne sais pas."}, {"type": "fin"}], sessions, h)
    assert not bad["ok"] and bad["outils_manquants"] == ["get_decisions|get_arbre_actions"]
