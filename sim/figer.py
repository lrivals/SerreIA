"""Frozen history of a scenario (docs/16 §2): `python -m sim --scenario mildiou --figer DIR`.

The scenario runs at full speed, ingested into `DIR/serre.db` (SQLite, seeded with
serre.yaml), and leaves next to it:
- `scenario.json`: name, start and end of the simulated time, seed, result of the check;
- `verification.txt`: the report of `sim.attendus`;
- `serre-demo.json`: the offline mode of the game view (`frontend/src/game/donnees.ts`,
  `Demo`): the greenhouse as the API serves it at the end of the run, and the actuator,
  decision, alert, vision and node events replayed in `demo_s` seconds.

`python -m backend.api --historique DIR` serves that database with the clock stopped at
the end of the run (UI and agent on a reproducible history).
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from .attendus import Resultat, rapport, verifier
from .scenario import Run, Scenario, run_fast

log = logging.getLogger(__name__)

DEMO_S = 240.0  # the whole run replayed in 4 min
DEMO_KINDS = {"etat", "decision", "alerte", "vision", "status"}
LAST = timedelta(seconds=1)


def figer(scenario: Scenario, out: Path, config: Path | None = None, extra_faults=(),
          demo_s: float = DEMO_S) -> tuple[Run, Resultat]:  # fmt: skip
    from backend.db.seed import seed
    from backend.db.session import init_db, make_engine, make_sessions
    from edge.controller.config import DEFAULT_CONFIG, load_greenhouse

    out.mkdir(parents=True, exist_ok=True)
    db = out / "serre.db"
    db.unlink(missing_ok=True)
    engine = make_engine(f"sqlite:///{db}")
    init_db(engine)
    sessions = make_sessions(engine)
    with sessions.begin() as s:
        seed(s, load_greenhouse(config or DEFAULT_CONFIG), scenario.debut)
    run = run_fast(scenario, sessions, config, extra_faults)
    res = verifier(run)
    (out / "verification.txt").write_text(rapport(run, res) + "\n")
    meta = dict(
        nom=scenario.nom,
        debut=scenario.debut.isoformat(),
        fin=run.sim.t.isoformat(),
        seed=scenario.seed,
        pannes=[*scenario.pannes, *extra_faults],
        ok=res.ok,
        ecarts=res.ecarts,
        connus=res.connus,
        consommation=run.consommation,
    )
    (out / "scenario.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=str))
    demo = demo_json(sessions, run, demo_s)
    (out / "serre-demo.json").write_text(json.dumps(demo, ensure_ascii=False))
    engine.dispose()
    return run, res


def end_of(historique: Path) -> datetime:
    """Last instant of a frozen history: the clock of its API (a run ending at 00:00
    shows its last day, not an empty one)."""
    fin = datetime.fromisoformat(json.loads((historique / "scenario.json").read_text())["fin"])
    return fin - LAST


def demo_json(sessions, run: Run, demo_s: float = DEMO_S) -> dict:
    """The `Demo` of the game view: `donnees` and `conso` read through the API at the end
    of the run, events of the bus compressed into `demo_s` seconds."""
    from fastapi.testclient import TestClient

    from backend.api.app import Settings, create_app
    from backend.live.bridge import event

    end = run.sim.t - LAST
    app = create_app(sessions, clock=lambda: end, settings=Settings(frontend=None))
    with TestClient(app) as client:

        def get(path: str, **params):
            r = client.get(f"/api{path}", params=params)
            r.raise_for_status()
            return r.json()

        zones = get("/zones")
        ids = [z["id"] for z in zones]
        serres = get("/serres")
        donnees = dict(
            serre=serres[0] if serres else None,
            zones=zones,
            plans=[get(f"/zones/{z}/plan") for z in ids],
            actionneurs=get("/actionneurs"),
            capteurs=get("/capteurs"),
            cameras=get("/cameras"),
            cuves=get("/cuves"),
            noeuds=get("/noeuds"),
            tableaux={z: get(f"/zones/{z}/tableau") for z in ids},
            alertes=get("/alertes", actives="true"),
            propositions=get("/decisions", statut="proposee"),
            avertissements=[],
        )
        conso = get("/consommation", periode="jour")

    start = run.scenario.debut
    scale = demo_s / max(1.0, (end - start).total_seconds())
    evenements = []
    for topic, payload in run.log:
        e = event(topic, payload)
        if e is None or e["kind"] not in DEMO_KINDS:
            continue
        ts = (e["payload"] or {}).get("ts") if isinstance(e["payload"], dict) else None
        t = (datetime.fromisoformat(ts) - start).total_seconds() if ts else None
        if t is None:  # node status: no timestamp, the time of the previous event
            t = evenements[-1]["t"] / scale if evenements else 0.0
        evenements.append(dict(t=round(t * scale, 2), evenement=e))
    evenements.sort(key=lambda x: x["t"])  # stable: the publication order within an instant
    return dict(donnees=donnees, conso=conso, evenements=evenements)
