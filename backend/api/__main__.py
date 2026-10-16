"""HTTP API (docs/12 §5).

python -m backend.api [--db URL] [--host pi.local] [--port 1883] [--http-port 8000]
python -m backend.api --mqtt none            # read-only: no validation, no manual action
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
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    engine = make_engine(args.db)
    init_db(engine)
    pub = None
    if args.mqtt == "broker":
        from edge.publisher import MqttPublisher

        pub = MqttPublisher(NODE, args.host, args.port)
    try:
        uvicorn.run(create_app(make_sessions(engine), pub), host=args.http_host,
                    port=args.http_port)  # fmt: skip
    finally:
        if pub is not None:
            pub.close()


if __name__ == "__main__":
    main()
