"""Greenhouse simulator on MQTT (docs/06 §5).

    python -m sim                                   # broker localhost:1883, real time
    python -m sim --accel 60                        # 1 simulated minute per second
    python -m sim --mqtt none --avec-controleur --accel 600 --duree-h 2
    python -m sim --panne fige:z1/temperature@30-90 --panne deconnexion:esp32-02@10-40

Publishes on the same topics as the ESP32 nodes and reacts to the commands. With
`--mqtt none` the simulator and the controller share an in-memory bus (no broker needed);
`--avec-controleur` runs edge.controller in the same process, on the simulated clock.

Scripted scenarios (docs/16, sim/scenarios/<nom>.yaml, sim/scenario.py):

    python -m sim --scenario journee --mqtt none --accel 0      # replayed and checked
    python -m sim --scenario mildiou --figer data/scenarios/mildiou/   # frozen history
    python -m sim --scenario journee --avec-controleur --accel 60      # live, on the broker

The scenario gives the start, duration, seed and faults (`--debut`, `--duree-h`, `--seed`
override them, `--panne` adds faults). In fast mode (`--mqtt none --accel 0`) the
controller is always attached and the run is checked against `<nom>.attendus.yaml`; the
exit code is 1 on a failure.
"""

import argparse
import logging
import signal
import sys
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
    parser.add_argument("--seed", type=int)
    parser.add_argument("--panne", action="append", default=[], help="voir sim/faults.py")
    parser.add_argument("--avec-controleur", action="store_true")
    parser.add_argument("--config", type=Path, help="serre.yaml du contrôleur")
    parser.add_argument("--scenario", help="nom (sim/scenarios/) ou chemin d'un scénario")
    parser.add_argument("--figer", type=Path, help="--scenario : écrire l'historique figé ici")
    parser.add_argument("-v", "--verbose", action="store_true", help="journaliser chaque message")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    scenario = None
    if args.scenario:
        from dataclasses import replace

        from .scenario import Scenario

        scenario = Scenario.load(args.scenario)
        if args.debut:
            scenario = _at(scenario, args.debut)
        if args.duree_h:
            scenario = replace(scenario, duree_h=args.duree_h)
        if args.seed is not None:
            scenario = replace(scenario, seed=args.seed)
        if args.figer or (args.mqtt == "none" and not args.accel):
            sys.exit(_fast(scenario, args))
    elif args.figer:
        parser.error("--figer demande --scenario")

    from edge.publisher import LoopbackBus, LoopbackPublisher, MqttPublisher

    if scenario is not None:
        start = scenario.debut
    else:
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

    if scenario is not None:
        faults, seed = scenario.faults(args.panne), scenario.seed
        duration_s = scenario.duree_h * 3600
    else:
        faults = Faults([parse_fault(s, start) for s in args.panne])
        seed = args.seed or 0
        duration_s = args.duree_h * 3600 if args.duree_h else None
    sim = Simulation(pub, start, seed, faults, controller=controller, scenario=scenario)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    try:
        sim.run(duration_s, args.accel or None, stop)
    except KeyboardInterrupt:
        pass
    finally:
        sim.close()
        pub.close()


def _at(scenario, debut: str):
    """The scenario moved to another start (every time keeps its offset)."""
    from dataclasses import replace

    t = datetime.fromisoformat(debut)
    if t.tzinfo is None:
        t = t.replace(tzinfo=scenario.debut.tzinfo)
    d = t - scenario.debut
    return replace(
        scenario,
        debut=t,
        nuages=[(a + d, b + d, c) for a, b, c in scenario.nuages],
        forcages=[replace(f, de=f.de + d, a=f.a + d if f.a else None) for f in scenario.forcages],
        vision=[replace(v, t=v.t + d) for v in scenario.vision],
    )


def _fast(scenario, args) -> int:
    """Fast mode: replayed at full speed and checked (frozen with --figer)."""
    from .attendus import rapport, verifier
    from .scenario import run_fast

    for name in ("edge", "httpx"):  # the report says what happened
        logging.getLogger(name).setLevel(logging.ERROR)
    if args.figer:
        from .figer import figer

        run, res = figer(scenario, args.figer, args.config, args.panne)
        print(rapport(run, res))
        print(f"historique figé : {args.figer}/ (serre.db, serre-demo.json, verification.txt)")
    else:
        run = run_fast(scenario, config=args.config, extra_faults=args.panne)
        res = verifier(run)
        print(rapport(run, res))
    return 0 if res.ok else 1


if __name__ == "__main__":
    main()
