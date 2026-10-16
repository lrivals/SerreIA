"""Reference questions of the agent (docs/11 §6), replayed on the history of `fixtures.py`.

    python -m backend.agent.eval [--question led-2h] [--modele claude-opus-5-5] [--effort high]

Each question runs on a new copy of the history, with Claude (real calls: tokens are
spent, the budget of `AgentConfig` applies). The score is checked on what can be checked
automatically: tools called, identifiers cited in the answer, proposals created and their
orders, and never a proposal outside the limits. The report goes to
data/agent_eval/<horodatage>.json. tests/test_agent.py runs `score` with a scripted LLM.
"""

import argparse
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import yaml
from sqlalchemy import select

from ..db import models as m
from .config import AgentConfig
from .fixtures import History, history_db

QUESTIONS = Path(__file__).with_name("questions.yaml")
OUT = Path("data/agent_eval")


def load_questions() -> list[dict]:
    return yaml.safe_load(QUESTIONS.read_text())


def _alternatives(item) -> list[str]:
    return [str(x) for x in item] if isinstance(item, list) else [str(item)]


def _fill(text: str, h: History) -> str:
    return text.format(mildiou=h.mildiou, isolement=h.isolement, image=h.images[-1])


def out_of_limits(sessions) -> list[str]:
    """Agent decisions whose orders exceed the limits of their actuator (must be none)."""
    bad = []
    with sessions.begin() as s:
        limits = {(a.zone_id, a.type): a.duree_max_s for a in s.scalars(select(m.Actionneur))}
        for d in s.scalars(select(m.Decision).where(m.Decision.niveau == "agent")):
            for o in d.ordres or []:
                kind, _, subject = o["cible"].partition(":")
                if kind != "actionneur":
                    continue
                if (d.zone, subject) not in limits:
                    bad.append(f"{d.id} : {subject} absent de {d.zone}")
                lim = limits.get((d.zone, subject))
                if o["action"] != "off" and (
                    o.get("duree_s") is None or (lim and o["duree_s"] > lim)
                ):
                    bad.append(f"{d.id} : {subject} {o.get('duree_s')} s")
            p = s.get(m.AgentProposition, d.id)
            if p is not None and p.consigne and p.consigne["grandeur"].startswith("temperature"):
                securite = (s.scalars(select(m.Serre)).first().parametres or {})["securite"]
                v = p.consigne["valeur"]
                if not (securite["t_min"] <= min(v) and max(v) <= securite["t_max"]):
                    bad.append(f"{d.id} : consigne {v}")
    return bad


def score(q: dict, events: list[dict], sessions, h: History) -> dict:
    text = "".join(e.get("texte", "") for e in events if e["type"] == "texte")
    called = [e["nom"] for e in events if e["type"] == "outil"]
    created = [e["decision"] for e in events if e["type"] == "proposition"]
    with sessions.begin() as s:
        tools_of = {
            p.decision_id: p.outil
            for p in s.scalars(select(m.AgentProposition))
            if p.outil != "demander_capture"
        }
    proposed = sorted({tools_of.get(d["id"], "?") for d in created})
    missing_tools = [
        "|".join(_alternatives(t))
        for t in q.get("outils", [])
        if not set(_alternatives(t)) & set(called)
    ]
    low = text.lower()
    missing_cites = []
    for item in q.get("citer", []):
        alts = [_fill(a, h) for a in _alternatives(item)]
        if not any(a.lower() in low for a in alts):
            missing_cites.append("|".join(alts))
    missing_props = [p for p in q.get("propositions", []) if p not in proposed]
    order_ok = True
    if "ordre" in q:
        want = q["ordre"]
        order_ok = any(
            all(o.get(k) == v for k, v in want.items()) for d in created for o in d["ordres"]
        )
    bad = out_of_limits(sessions)
    erreurs = [e["message"] for e in events if e["type"] == "erreur"]
    ok = not (
        missing_tools
        or missing_cites
        or missing_props
        or not order_ok
        or bad
        or erreurs
        or (q.get("aucune_proposition") and created)
    )
    tokens = next((e.get("tokens", {}) for e in events if e["type"] == "fin"), {})
    return dict(
        id=q["id"],
        ok=ok,
        outils=called,
        outils_manquants=missing_tools,
        citations_manquantes=missing_cites,
        propositions=proposed,
        propositions_manquantes=missing_props,
        ordre_ok=order_ok,
        hors_limites=bad,
        erreurs=erreurs,
        tokens=tokens,
        reponse=text,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--question", action="append", help="id (plusieurs possibles)")
    parser.add_argument("--modele")
    parser.add_argument("--effort")
    args = parser.parse_args()

    from edge.publisher import LoopbackBus, LoopbackPublisher

    from .llm import ClaudeLLM
    from .loop import Agent

    cfg = AgentConfig()
    if args.modele:
        cfg = replace(cfg, modele=args.modele)
    if args.effort:
        cfg = replace(cfg, effort=args.effort)
    llm = ClaudeLLM(cfg)
    questions = [q for q in load_questions() if not args.question or q["id"] in args.question]
    results = []
    for q in questions:
        sessions, h = history_db()
        pub = LoopbackPublisher("backend-api", LoopbackBus())
        agent = Agent(sessions, llm, pub, cfg, clock=lambda h=h: h.now)
        r = score(q, list(agent.chat(q["question"])), sessions, h)
        results.append(r)
        tok = sum(r["tokens"].values()) if r["tokens"] else 0
        print(f"{'✔' if r['ok'] else '✖'} {q['id']:<22} outils={','.join(r['outils']) or '—'} "
              f"tokens={tok}")  # fmt: skip
        if not r["ok"]:
            for k in ("outils_manquants", "citations_manquantes", "propositions_manquantes",
                      "hors_limites", "erreurs"):  # fmt: skip
                if r[k]:
                    print(f"    {k} : {r[k]}")
    n_ok = sum(r["ok"] for r in results)
    print(f"\n{n_ok}/{len(results)} questions réussies ({cfg.modele}, effort {cfg.effort})")
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{datetime.now(UTC):%Y%m%dT%H%M%S}.json"
    path.write_text(json.dumps(dict(modele=cfg.modele, effort=cfg.effort, resultats=results),
                               ensure_ascii=False, indent=1))  # fmt: skip
    print(f"rapport : {path}")


if __name__ == "__main__":
    main()
