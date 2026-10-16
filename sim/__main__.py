"""Greenhouse simulator on MQTT (docs/06 §5).

    python -m sim                                   # broker localhost:1883, real time
    python -m sim --accel 60                        # 1 simulated minute per second
    python -m sim --mqtt none --avec-controleur --accel 600 --duree-h 2
    python -m sim --panne fige:z1/temperature@30-90 --panne deconnexion:esp32-02@10-40

Publishes on the same topics as the ESP32 nodes and reacts to the commands. With
`--mqtt none` the simulator and the controller share an in-memory bus (no broker needed);
`--avec-controleur` runs edge.controller in the same process, on the simulated clock.
"""

import argparse
import logging
import signal
import threading
from datetime import UTC, datetime
from pathlib import Path

from .faults import Faults, parse_fault
from .simulation import Simulation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mqtt", choices=["broker", "none"], default="broker")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--accel", type=float, default=1.0, help="facteur de temps (0 : max)")
    parser.add_argument("--duree-h", type=float, help="durée simulée (h), défaut : infinie")
    parser.add_argument("--debut", help="date de début ISO (défaut : maintenant)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--panne", action="append", default=[], help="voir sim/faults.py")
    parser.add_argument("--avec-controleur", action="store_true")
    parser.add_argument("--config", type=Path, help="serre.yaml du contrôleur")
    parser.add_argument("-v", "--verbose", action="store_true", help="journaliser chaque message")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    from edge.publisher import LoopbackBus, LoopbackPublisher, MqttPublisher

    start = datetime.fromisoformat(args.debut) if args.debut else datetime.now(UTC)
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    bus = None
    if args.mqtt == "none":
        bus = LoopbackBus()
        pub = LoopbackPublisher("sim", bus)
    else:
        pub = MqttPublisher("sim", args.host, args.port)

    controller = None
    if args.avec_controleur:
        from edge.controller.config import DEFAULT_CONFIG
        from edge.controller.service import NODE, build

        cpub = LoopbackPublisher(NODE, bus) if bus else MqttPublisher(NODE, args.host, args.port)
        controller = build(args.config or DEFAULT_CONFIG, cpub)
    if bus is not None:
        log = logging.getLogger("bus")

        def show(topic: str, payload: bytes) -> None:  # alerts always; everything with -v
            if args.verbose or topic.endswith("/alerte"):
                log.info("%s %s", topic, payload.decode())

        bus.subscribe("serre/#", show)

    faults = Faults([parse_fault(s, start) for s in args.panne])
    sim = Simulation(pub, start, args.seed, faults, controller=controller)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    try:
        sim.run(args.duree_h * 3600 if args.duree_h else None, args.accel or None, stop)
    except KeyboardInterrupt:
        pass
    finally:
        sim.close()
        pub.close()


if __name__ == "__main__":
    main()
