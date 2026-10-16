"""HTTP API (docs/12 §5).

python -m backend.api [--db URL] [--host pi.local] [--port 1883] [--http-port 8000]
python -m backend.api --mqtt none            # read-only: no validation, no manual action
python -m backend.api --agent none           # without the conversational agent (docs/11)

The agent uses Claude (`SERREIA_AGENT_MODEL`, default claude-sonnet-5-5) with the
credentials of the Anthropic SDK (`ANTHROPIC_API_KEY` or an `ant auth login` profile);
without the `anthropic` package the /agent routes answer 503, the rest works the same.
"""

import argparse
import logging

import uvicorn

from ..db.session import init_db, make_engine, make_sessions
from .app import create_app

NODE = "backend-api"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", help="URL SQLAlchemy (défaut : $SERREIA_DB)")
    parser.add_argument("--mqtt", choices=["broker", "none"], default="broker")
    parser.add_argument("--host", default="localhost", help="broker MQTT")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--http-host", default="127.0.0.1")
    parser.add_argument("--http-port", type=int, default=8000)
    parser.add_argument("--agent", choices=["claude", "none"], default="claude")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    engine = make_engine(args.db)
    init_db(engine)
    pub = None
    if args.mqtt == "broker":
        from edge.publisher import MqttPublisher

        pub = MqttPublisher(NODE, args.host, args.port)
    sessions = make_sessions(engine)
    agent = _agent(sessions, pub) if args.agent == "claude" else None
    try:
        uvicorn.run(create_app(sessions, pub, agent=agent), host=args.http_host,
                    port=args.http_port)  # fmt: skip
    finally:
        if pub is not None:
            pub.close()


def _agent(sessions, pub):
    from ..agent.config import AgentConfig
    from ..agent.loop import Agent

    try:
        from ..agent.llm import ClaudeLLM

        llm = ClaudeLLM(AgentConfig())
    except ImportError:
        logging.warning("paquet anthropic absent : agent désactivé (pip install anthropic)")
        return None
    logging.info("agent : %s", llm.modele)
    return Agent(sessions, llm, pub)


if __name__ == "__main__":
    main()
