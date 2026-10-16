"""Camera service of the Pi (docs/05 §3), run as a systemd service.

    python -m edge.camera_service --config edge/config.yaml [--once] [--mqtt none]
        [--camera cam-z1-a] [--backend onnx|hailo]

Loop: scheduled captures every `periode_s` per camera, plus on-demand captures received on
`serre/<zone>/cmd/capture`. For each capture: LEDs switched off (mode "couper", retained
state restored afterwards), grey-card white balance, inference (edge.vision.pipeline),
publication on `serre/<zone>/vision/<camera>`, local archive (7 days) and asynchronous upload.
Repeated failures of a camera raise a `warning` alert on `serre/<zone>/alerte`.
On the PC: `--mqtt none` (no broker) and a `folder:` camera source.
"""

import argparse
import logging
import queue
import signal
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from common.mqtt import (
    Actuator,
    ActuatorState,
    Alert,
    CaptureRequest,
    Command,
    VisionResult,
    alert_topic,
    capture_topic,
    cmd_topic,
    decode,
    parse_topic,
    state_topic,
    vision_topic,
)

from .archive import Archive, Uploader, http_send
from .cameras import Camera, open_camera
from .config import CameraCfg, ServiceCfg, load_config
from .publisher import Publisher, make_publisher
from .sdnotify import sd_notify
from .vision.pipeline import EdgePipeline, Plant
from .vision.preprocess import gray_card_wb

log = logging.getLogger("camera_service")

SOURCE = "camera_service"
PURGE_PERIOD_S = 3600.0


def utc_now() -> datetime:
    return datetime.now(UTC)


class CameraService:
    def __init__(
        self,
        cfg: ServiceCfg,
        pipeline: EdgePipeline,
        publisher: Publisher,
        cameras: dict[str, Camera],
        archive: Archive,
        clock: Callable[[], datetime] = utc_now,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.cfg, self.pipeline, self.publisher = cfg, pipeline, publisher
        self.cameras, self.archive = cameras, archive
        self.clock, self.sleep = clock, sleep
        self.cams = {c.id: c for c in cfg.cameras if c.id in cameras}
        self.next_due = dict.fromkeys(self.cams, 0.0)  # monotonic seconds; 0: right away
        self.requests: queue.Queue[str] = queue.Queue()
        self.led_state: dict[str, ActuatorState] = {}
        self.errors = dict.fromkeys(self.cams, 0)
        self.stop_event = threading.Event()
        self._last_purge = float("-inf")

    # --- MQTT ----------------------------------------------------------------

    def subscribe(self) -> None:
        for zone in sorted({c.zone for c in self.cams.values()}):
            self.publisher.subscribe(capture_topic(zone), self.on_capture)
            if self.cfg.led.mode == "couper":
                self.publisher.subscribe(state_topic(zone, Actuator.LED), self.on_led_state)

    def on_capture(self, topic: str, payload: bytes) -> None:
        """MQTT thread: queue the cameras of the zone (or the one requested)."""
        req = decode(topic, payload)
        assert isinstance(req, CaptureRequest)
        zone = parse_topic(topic).scope
        targets = [c.id for c in self.cams.values() if c.zone == zone
                   and (req.camera is None or c.id == req.camera)]  # fmt: skip
        if not targets:
            log.warning("capture demandée pour une caméra inconnue : %s %s", topic, req.camera)
        for cam_id in targets:
            log.info("capture à la demande %s (source %s)", cam_id, req.source)
            self.requests.put(cam_id)

    def on_led_state(self, topic: str, payload: bytes) -> None:
        state = decode(topic, payload)
        assert isinstance(state, ActuatorState)
        self.led_state[parse_topic(topic).scope] = state

    # --- capture -------------------------------------------------------------

    def _command(self, action: str, valeur: float | None, raison: str) -> Command:
        return Command(ts=self.clock(), action=action, valeur=valeur, source=SOURCE, raison=raison)

    @contextmanager
    def controlled_light(self, zone: str):
        """LEDs off during the capture, then their retained state restored.

        Without a known state (no retained `etat/led` received) the LEDs are left alone:
        better a tinted image than LEDs left off.
        """
        prev = self.led_state.get(zone) if self.cfg.led.mode == "couper" else None
        if prev is None or prev.action == "off":
            if self.cfg.led.mode == "couper" and prev is None:
                log.warning("état des LED de %s inconnu : capture sans couper l'éclairage", zone)
            yield
            return
        topic = cmd_topic(zone, Actuator.LED)
        self.publisher.publish(topic, self._command("off", None, "capture d'image"))
        try:
            self.sleep(self.cfg.led.attente_s)
            yield
        finally:
            self.publisher.publish(topic, self._command(prev.action, prev.valeur, "fin de capture"))

    def capture(self, cam: CameraCfg) -> VisionResult | None:
        try:
            with self.controlled_light(cam.zone):
                ts = self.clock()
                img = self.cameras[cam.id].capture()
            if cam.wb_roi is not None:
                img = gray_card_wb(img, cam.wb_roi)
            plants = [Plant(p.id, p.roi, p.px_per_cm, p.base_row) for p in cam.plantes]
            result, extras = self.pipeline(img, cam.id, ts, plants)
            source = getattr(self.cameras[cam.id], "last", None)
            if source is not None:
                extras["source"] = str(source)
            self.archive.save(img, result, extras)
            self.publisher.publish(vision_topic(cam.zone, cam.id), result)
        except Exception as e:
            self.errors[cam.id] += 1
            log.exception("capture %s échouée (%d de suite)", cam.id, self.errors[cam.id])
            if self.errors[cam.id] == self.cfg.erreurs_avant_alerte:
                self.publisher.publish(alert_topic(cam.zone), Alert(
                    ts=self.clock(), niveau="warning", source=f"{SOURCE}/{self.cfg.noeud}",
                    message=f"caméra {cam.id} : {self.errors[cam.id]} échecs de suite ({e})",
                ))  # fmt: skip
            return None
        self.errors[cam.id] = 0
        log.info(
            "%s : %d détection(s) dont %d anormale(s), anomalie %.2f, surface %d px",
            result.image_id, len(result.detections),
            sum(d.sante == "anormal" for d in result.detections),
            result.score_anomalie, result.surface_verte_px,
        )  # fmt: skip
        return result

    def run_once(self) -> list[VisionResult | None]:
        return [self.capture(cam) for cam in self.cams.values()]

    def step(self, now: float) -> float:
        """Due and requested captures; returns the wait until the next due capture."""
        while True:
            try:
                cam_id = self.requests.get_nowait()
            except queue.Empty:
                break
            self.capture(self.cams[cam_id])
        for cam_id, due in self.next_due.items():
            if now >= due:
                self.capture(self.cams[cam_id])
                self.next_due[cam_id] = now + self.cfg.periode_s
        if now - self._last_purge >= PURGE_PERIOD_S:
            if n := self.archive.purge(self.clock()):
                log.info("archive : %d jour(s) purgé(s)", n)
            self._last_purge = now
        return max(0.0, min(self.next_due.values()) - now)

    def run_forever(self, monotonic: Callable[[], float] = time.monotonic) -> None:
        sd_notify("READY=1")
        while not self.stop_event.is_set():
            wait = self.step(monotonic())
            sd_notify("WATCHDOG=1")
            try:  # wake up early on an on-demand capture
                self.requests.put(self.requests.get(timeout=min(wait, 5.0)))
            except queue.Empty:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=Path("edge/config.yaml"))
    parser.add_argument("--once", action="store_true", help="une capture par caméra puis sortie")
    parser.add_argument("--mqtt", choices=["broker", "none"], default="broker",
                        help="none : pas de broker, messages journalisés")  # fmt: skip
    parser.add_argument("--camera", action="append", help="limiter à ces caméras")
    parser.add_argument("--backend", choices=["onnx", "hailo"], default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")  # fmt: skip

    from .vision.bundle import build_pipeline

    cfg = load_config(args.config)
    if args.camera:
        cfg.cameras = [c for c in cfg.cameras if c.id in args.camera]
    m = cfg.modeles
    pipeline = build_pipeline(
        cfg.resolve(m.dir), args.backend or m.backend, cfg.seuils.conf_detection,
        cfg.seuils.marge_crop, m.patchcore, m.device,
    )  # fmt: skip
    log.info("modèle %s (%s)", pipeline.modele, args.backend or m.backend)
    cameras = {c.id: open_camera(c.source, c.resolution) for c in cfg.cameras}
    a = cfg.archive
    archive = Archive(cfg.resolve(a.dir), a.retention_jours, a.cote_max_px, a.qualite_jpeg)
    publisher = make_publisher(args.mqtt, cfg.noeud, cfg.mqtt.host, cfg.mqtt.port,
                               cfg.mqtt.keepalive_s)  # fmt: skip
    service = CameraService(cfg, pipeline, publisher, cameras, archive)
    uploader = None
    if cfg.upload.url:
        uploader = Uploader(archive, http_send(cfg.upload.url, cfg.upload.timeout_s),
                            cfg.upload.periode_s)  # fmt: skip
    try:
        if args.once:
            service.run_once()
            if uploader:
                uploader.upload_pending()
            return
        signal.signal(signal.SIGTERM, lambda *_: service.stop_event.set())
        service.subscribe()
        if uploader:
            uploader.start()
        service.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if uploader:
            uploader.stop()
        for cam in cameras.values():
            cam.close()
        publisher.close()


if __name__ == "__main__":
    main()
