"""HTTP API and web UI (docs/12).

python -m backend.api [--db URL] [--host pi.local] [--port 1883] [--http-port 8000]
python -m backend.api --mqtt none            # read-only: no validation, no manual action
python -m backend.api --mqtt sim             # simulated greenhouse, no broker (docs/12 §5)
python -m backend.api --mqtt sim --panne maladie:z1-A1/tomate/maladie/mildiou@15
python -m backend.api --mqtt sim --scenario journee --accel 60   # scripted scenario (docs/16)
python -m backend.api --historique data/scenarios/mildiou       # frozen history, read-only
python -m backend.api --agent none           # without the conversational agent (docs/11)
python -m backend.api --openapi frontend/src/api/openapi.json   # schema for the front

The UI is served on the same port once built (`make front-build`). `SERREIA_UI_PASSWORD`
protects the writes (docs/12 §1). `--install` / `--rsync`: where `POST
/api/config/publier` installs serre.yaml (local controller, Pi).

The agent uses Claude (`SERREIA_AGENT_MODEL`, default claude-sonnet-5-5) with the
credentials of the Anthropic SDK (`ANTHROPIC_API_KEY` or an `ant auth login` profile);
without the `anthropic` package the /agent routes answer 503, the rest works the same.
"""

import argparse
import json
import logging
import os
from pathlib import Path

import uvicorn

from ..db.session import init_db, make_engine, make_sessions
from .app import Settings, create_app

NODE = "backend-api"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", help="URL SQLAlchemy (défaut : $SERREIA_DB)")
    parser.add_argument("--mqtt", choices=["broker", "sim", "none"], default="broker")
    parser.add_argument("--host", default="localhost", help="broker MQTT")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--http-host", default="127.0.0.1")
    parser.add_argument("--http-port", type=int, default=8000)
    parser.add_argument("--agent", choices=["claude", "none"], default="claude")
    parser.add_argument("--images", type=Path, help="captures reçues (défaut : data/images)")
    parser.add_argument("--install", type=Path, help="serre.yaml installé à la publication")
    parser.add_argument("--rsync", help="destination rsync de serre.yaml à la publication")
    parser.add_argument(
        "--config-out", type=Path, help="versions de serre.yaml (data/serre_config)"
    )
    parser.add_argument("--config", type=Path, help="--mqtt sim : serre.yaml du contrôleur")
    parser.add_argument("--accel", type=float, default=1.0, help="--mqtt sim : facteur")
    parser.add_argument("--prefill-h", type=float,
                        help="--mqtt sim : heures simulées d'avance au démarrage "
                             "(défaut 24, 0 avec --scenario)")  # fmt: skip
    parser.add_argument("--panne", action="append", default=[],
                        help="--mqtt sim : panne de sim/faults.py")  # fmt: skip
    parser.add_argument("--scenario", help="--mqtt sim : scénario de sim/scenarios/ (docs/16)")
    parser.add_argument("--historique", type=Path,
                        help="historique figé d'un scénario (sim --figer) : sa base, "
                             "horloge arrêtée à sa fin, lecture seule")  # fmt: skip
    parser.add_argument("--openapi", type=Path, help="écrire le schéma OpenAPI et sortir")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    settings = Settings(password=os.environ.get("SERREIA_UI_PASSWORD") or None,
                        config_install=args.install, config_rsync=args.rsync)  # fmt: skip
    if args.images:
        settings.images = args.images
    if args.config_out:
        settings.config_out = args.config_out
    if args.openapi:
        app = create_app(make_sessions(make_engine("sqlite://")), settings=settings)
        args.openapi.parent.mkdir(parents=True, exist_ok=True)
        args.openapi.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=1))
        return

    clock = None
    if args.historique:
        from sim.figer import end_of

        args.db, args.mqtt = f"sqlite:///{args.historique / 'serre.db'}", "none"
        end = end_of(args.historique)
        clock = lambda: end  # noqa: E731
        logging.info("historique figé %s, horloge arrêtée à %s", args.historique, end)
    engine = make_engine(args.db)
    init_db(engine)
    sessions = make_sessions(engine)
    pub, runner = None, None
    if args.mqtt == "broker":
        from edge.publisher import MqttPublisher

        pub = MqttPublisher(NODE, args.host, args.port)
    elif args.mqtt == "sim":
        runner = _simulation(sessions, args)
        pub, clock = runner.publisher, runner.clock
    agent = _agent(sessions, pub, clock) if args.agent == "claude" else None
    try:
        app = create_app(sessions, pub, clock=clock, agent=agent, settings=settings)
        uvicorn.run(app, host=args.http_host, port=args.http_port)
    finally:
        if runner is not None:
            runner.close()
        elif pub is not None:
            pub.close()


def _simulation(sessions, args):
    from edge.controller.config import DEFAULT_CONFIG, load_greenhouse

    from ..db.seed import seed
    from .sim import SimRunner

    scenario = None
    if args.scenario:
        from sim.scenario import Scenario

        scenario = Scenario.load(args.scenario)
    with sessions.begin() as s:  # a scenario in the past: plants placed before its start
        seed(s, load_greenhouse(args.config or DEFAULT_CONFIG),
             scenario.debut if scenario else None)  # fmt: skip
    prefill = args.prefill_h if args.prefill_h is not None else (0.0 if scenario else 24.0)
    runner = SimRunner(sessions, args.config, args.accel, prefill, pannes=args.panne,
                       scenario=scenario)  # fmt: skip
    runner.start()
    return runner


def _agent(sessions, pub, clock=None):
    from ..agent.config import AgentConfig
    from ..agent.loop import Agent

    try:
        from ..agent.llm import ClaudeLLM

        llm = ClaudeLLM(AgentConfig())
    except ImportError:
        logging.warning("paquet anthropic absent : agent désactivé (pip install anthropic)")
        return None
    logging.info("agent : %s", llm.modele)
    return Agent(sessions, llm, pub, clock=clock)


if __name__ == "__main__":
    main()
