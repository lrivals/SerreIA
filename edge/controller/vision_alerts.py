"""From vision predictions to alerts (docs/05 §4): temporal smoothing and sensor fusion.

    python -m edge.controller.vision_alerts [--mqtt none]
    python -m edge.controller.vision_alerts --replay edge/archive   # PC: replays the archive

- Smoothing: a camera is "abnormal" only when an `anormal` detection has
  `sante_conf > seuil` on N = 3 consecutive captures (or on average over the last N):
  reflections and shadows of a single capture are not enough.
- Levels (contract: info | warning | critique): isolated abnormal capture -> info (log);
  persistent -> warning (dashboard); persistent + a humid-weather disease (mildiou…)
  + air humidity > 85 % for more than 6 h -> critique (notification).
- An alert is published only when the level of a camera changes; going back to normal
  after a warning or a critique is reported as info. The humidity escalation is evaluated
  at the next capture of the camera.
- A camera that only sees species outside the taxonomy (docs/09 §2, `serre.yaml`) is
  smoothed on `score_anomalie` instead of the classifier health, and its level stops at
  warning: a simple alert, no disease class to trust.
"""

import argparse
import json
import logging
import signal
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from common.mqtt import (
    SUBSCRIPTIONS,
    Alert,
    SensorReading,
    SensorType,
    TopicKind,
    VisionResult,
    alert_topic,
    decode,
    parse_topic,
)

log = logging.getLogger("vision_alerts")

Level = Literal["info", "warning", "critique"]
SOURCE = "vision_alerts"


@dataclass(frozen=True)
class VisionAlertConfig:
    seuil: float = 0.6  # sante_conf of an `anormal` detection
    n: int = 3
    mode: Literal["consecutif", "moyenne"] = "consecutif"
    hr_seuil: float = 85.0  # %
    hr_duree_h: float = 6.0
    # Diseases favoured by a wet atmosphere (last segment of the taxonomy class).
    maladies_humides: tuple[str, ...] = ("mildiou", "cladosporiose", "septoriose")


def abnormal_score(result: VisionResult) -> float:
    """Highest sante_conf of the `anormal` detections, 0 without any."""
    return max((d.sante_conf for d in result.detections if d.sante == "anormal"), default=0.0)


def dominant_class(result: VisionResult) -> str | None:
    abn = [d for d in result.detections if d.sante == "anormal"]
    return max(abn, key=lambda d: d.sante_conf).classe if abn else None


class VisionSmoother:
    """Per camera history of the last N abnormal scores."""

    def __init__(self, n: int = 3, seuil: float = 0.6, mode: str = "consecutif"):
        self.n, self.seuil, self.mode = n, seuil, mode
        self.hist: dict[str, deque[float]] = {}

    def update(self, camera: str, score: float) -> tuple[bool, bool]:
        """(abnormal now, persistent)."""
        h = self.hist.setdefault(camera, deque(maxlen=self.n))
        h.append(score)
        full = len(h) == self.n
        if self.mode == "moyenne":
            persistent = full and sum(h) / self.n > self.seuil
        else:
            persistent = full and all(s > self.seuil for s in h)
        return score > self.seuil, persistent


class HumidityTracker:
    """Start of the current spell above the threshold, per zone."""

    def __init__(self, seuil: float = 85.0):
        self.seuil = seuil
        self.since: dict[str, datetime | None] = {}

    def update(self, zone: str, reading: SensorReading) -> None:
        if reading.qualite == "erreur":
            return
        if reading.valeur > self.seuil:
            if self.since.get(zone) is None:
                self.since[zone] = reading.ts
        else:
            self.since[zone] = None

    def duration(self, zone: str, now: datetime) -> timedelta:
        start = self.since.get(zone)
        return now - start if start is not None else timedelta(0)


@dataclass
class VisionAlerter:
    cfg: VisionAlertConfig = field(default_factory=VisionAlertConfig)
    # Greenhouse.vision_auto: False for a camera that only sees out-of-taxonomy species.
    vision_auto: Callable[[str], bool] = lambda camera: True

    def __post_init__(self):
        self.smoother = VisionSmoother(self.cfg.n, self.cfg.seuil, self.cfg.mode)
        self.humidity = HumidityTracker(self.cfg.hr_seuil)
        self.level: dict[str, Level | None] = {}

    def on_sensor(self, zone: str, sensor: str, reading: SensorReading) -> None:
        if sensor == SensorType.HUMIDITE:
            self.humidity.update(zone, reading)

    def on_vision(self, zone: str, result: VisionResult) -> Alert | None:
        cam = result.camera
        auto = self.vision_auto(cam)
        score = abnormal_score(result) if auto else result.score_anomalie
        now_abn, persistent = self.smoother.update(cam, score)
        classe = dominant_class(result) if auto else None
        humid = self.humidity.duration(zone, result.ts)
        humid_disease = (
            classe is not None and classe.rsplit("/", 1)[-1] in self.cfg.maladies_humides
        )
        level: Level | None = None
        if persistent:
            level = "warning"
            if humid_disease and humid >= timedelta(hours=self.cfg.hr_duree_h):
                level = "critique"
        elif now_abn:
            level = "info"

        prev = self.level.get(cam)
        self.level[cam] = level
        if level == prev:
            return None
        if level is None:
            if prev in ("warning", "critique"):
                return Alert(ts=result.ts, niveau="info", source=f"{SOURCE}/{cam}",
                             message=f"{cam} : retour à la normale")  # fmt: skip
            return None
        what = classe or ("anomalie" if auto else "score d'anomalie")
        msg = f"{cam} : {what} ({score:.2f})"
        if level == "info":
            msg += " sur une capture isolée"
        else:
            msg += f" sur {self.cfg.n} captures"
        if level == "critique":
            msg += (
                f", humidité > {self.cfg.hr_seuil:g} % depuis {humid.total_seconds() / 3600:.1f} h"
            )
        return Alert(ts=result.ts, niveau=level, message=msg, source=f"{SOURCE}/{cam}")

    def on_message(self, topic: str, payload: bytes) -> tuple[str, Alert] | None:
        """Contract message -> (alert topic, alert) to publish, if any."""
        parsed = parse_topic(topic)
        message = decode(topic, payload)
        if parsed.kind is TopicKind.CAPTEUR:
            self.on_sensor(parsed.scope, parsed.subject, message)
            return None
        if parsed.kind is TopicKind.VISION:
            alert = self.on_vision(parsed.scope, message)
            return (alert_topic(parsed.scope), alert) if alert else None
        return None


def replay(alerter: VisionAlerter, archive: Path, zone: str) -> list[Alert]:
    """Feeds the archived VisionResults (edge/archive.py) in time order."""
    results = []
    for path in sorted(archive.rglob("*.json")):
        try:
            results.append(VisionResult.model_validate(json.loads(path.read_text())["resultat"]))
        except (KeyError, ValueError):
            continue
    alerts = []
    for r in sorted(results, key=lambda r: r.ts):
        if alert := alerter.on_vision(zone, r):
            log.info("[%s] %s", alert.niveau, alert.message)
            alerts.append(alert)
    return alerts


def _vision_auto(path: Path | None) -> Callable[[str], bool]:
    """`Greenhouse.vision_auto` of the (hot reloaded) serre.yaml; without a readable
    configuration, every camera keeps the default behaviour."""
    import yaml

    from .config import DEFAULT_CONFIG, ConfigWatcher

    try:
        watcher = ConfigWatcher(path or DEFAULT_CONFIG)
    except (OSError, ValueError, KeyError, yaml.YAMLError) as e:
        log.warning("serre.yaml illisible (%s) : toutes les caméras en mode standard", e)
        return lambda camera: True
    return lambda camera: watcher.get().vision_auto(camera)


def main() -> None:
    from edge.config import ROOT
    from edge.publisher import make_publisher
    from edge.sdnotify import sd_notify

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mqtt", choices=["broker", "none"], default="broker")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--replay", type=Path, help="rejouer une archive au lieu de MQTT")
    parser.add_argument("--zone", default="z1", help="zone des résultats rejoués")
    parser.add_argument("--seuil", type=float, default=VisionAlertConfig.seuil)
    parser.add_argument("--n", type=int, default=VisionAlertConfig.n)
    parser.add_argument("--mode", choices=["consecutif", "moyenne"], default="consecutif")
    parser.add_argument("--config", type=Path, help="serre.yaml (caméras, espèces vues)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    alerter = VisionAlerter(
        VisionAlertConfig(seuil=args.seuil, n=args.n, mode=args.mode),
        vision_auto=_vision_auto(args.config),
    )
    if args.replay:
        path = args.replay if args.replay.is_absolute() else ROOT / args.replay
        print(f"{len(replay(alerter, path, args.zone))} alerte(s)")
        return

    pub = make_publisher(args.mqtt, SOURCE.replace("_", "-"), args.host, args.port)

    def handle(topic: str, payload: bytes) -> None:
        if out := alerter.on_message(topic, payload):
            pub.publish(*out)

    pub.subscribe(SUBSCRIPTIONS[TopicKind.VISION], handle)
    pub.subscribe(f"serre/+/capteur/{SensorType.HUMIDITE}", handle)
    sd_notify("READY=1")
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    try:
        while not stop.wait(10):
            sd_notify("WATCHDOG=1")
    except KeyboardInterrupt:
        pass
    finally:
        pub.close()


if __name__ == "__main__":
    main()
