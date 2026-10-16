"""Camera service (docs/05 §3, §6): fake camera, pipeline and publisher; archive and upload."""

import json
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from common.mqtt import (
    ActuatorState,
    Alert,
    Command,
    VisionResult,
    capture_topic,
    decode,
    encode,
    state_topic,
)
from edge.archive import Archive, Uploader
from edge.camera_service import CameraService
from edge.cameras import FolderCamera, open_camera
from edge.config import ServiceCfg, load_config
from edge.publisher import DryRunPublisher
from edge.vision.pipeline import EdgePipeline

T0 = datetime(2026, 10, 12, 14, 0, tzinfo=UTC)


def fake_classifier(crops):
    return [{"espece": "tomate", "espece_conf": 0.9, "sante": "sain", "sante_conf": 0.95,
             "classe": "tomate/sain/sain", "classe_conf": 0.9, "p_anormal": 0.05,
             "entropie": 0.2} for _ in crops]  # fmt: skip


class FakeCamera:
    def __init__(self, fail=False):
        self.n, self.fail = 0, fail

    def capture(self):
        self.n += 1
        if self.fail:
            raise OSError("caméra débranchée")
        return np.full((60, 80, 3), (50, 150, 40), np.uint8)

    def close(self):
        pass


class Clock:
    def __init__(self):
        self.t = T0

    def __call__(self):
        self.t += timedelta(seconds=1)
        return self.t


def make_service(tmp_path, led="aucun", fail=False, **cfg):
    config = ServiceCfg.model_validate({
        "cameras": [{"id": "cam-z1-a", "zone": "z1", "source": "usb:0"},
                    {"id": "cam-z2-a", "zone": "z2", "source": "usb:1"}],
        "led": {"mode": led, "attente_s": 2},
        **cfg,
    })  # fmt: skip
    pub = DryRunPublisher("pi-test")
    sleeps = []
    service = CameraService(
        config, EdgePipeline(fake_classifier, "clf-test-v1"), pub,
        {c.id: FakeCamera(fail) for c in config.cameras}, Archive(tmp_path / "archive"),
        clock=Clock(), sleep=sleeps.append,
    )  # fmt: skip
    return service, pub, sleeps


def test_run_once_publishes_and_archives(tmp_path):
    service, pub, _ = make_service(tmp_path)
    results = service.run_once()
    assert all(isinstance(r, VisionResult) for r in results)
    assert [t for t, _ in pub.published] == ["serre/z1/vision/cam-z1-a", "serre/z2/vision/cam-z2-a"]
    for topic, payload in pub.published:
        assert isinstance(decode(topic, payload), VisionResult)
    records = list(service.archive.records())
    assert len(records) == 2 and all(p.with_suffix(".jpg").exists() for p in records)
    rec = json.loads(records[0].read_text())
    assert rec["resultat"]["modele"] == "clf-test-v1"
    assert rec["extras"]["classifieur"][0]["entropie"] == 0.2


def test_schedule_and_on_demand(tmp_path):
    service, pub, _ = make_service(tmp_path, periode_s=600)
    assert service.step(0.0) == 600  # both cameras due right away
    assert service.step(10.0) == 590 and len(pub.published) == 2
    req = {"ts": "2026-10-12T14:00:00Z", "source": "dashboard", "camera": None}
    service.on_capture(capture_topic("z2"), json.dumps(req).encode())
    service.step(20.0)
    assert pub.published[-1][0] == "serre/z2/vision/cam-z2-a" and len(pub.published) == 3
    service.on_capture(capture_topic("z1"), json.dumps({**req, "camera": "cam-inconnue"}).encode())
    assert service.requests.empty()
    service.step(600.0)
    assert len(pub.published) == 5


def test_led_switched_off_then_restored(tmp_path):
    service, pub, sleeps = make_service(tmp_path, led="couper")
    service.capture(service.cams["cam-z1-a"])  # LED state unknown: left alone
    assert [t for t, _ in pub.published] == ["serre/z1/vision/cam-z1-a"] and not sleeps

    state = ActuatorState(ts=T0, action="pwm", valeur=60)
    service.on_led_state(state_topic("z1", "led"), encode(state))
    pub.published.clear()
    service.capture(service.cams["cam-z1-a"])
    topics = [t for t, _ in pub.published]
    assert topics == ["serre/z1/cmd/led", "serre/z1/cmd/led", "serre/z1/vision/cam-z1-a"]
    off, back = (decode(t, p) for t, p in pub.published[:2])
    assert isinstance(off, Command) and off.action == "off"
    assert back.action == "pwm" and back.valeur == 60
    assert sleeps == [2]


def test_repeated_failures_raise_one_alert(tmp_path):
    service, pub, _ = make_service(tmp_path, fail=True, erreurs_avant_alerte=3)
    cam = service.cams["cam-z1-a"]
    for _ in range(4):
        assert service.capture(cam) is None
    alerts = [decode(t, p) for t, p in pub.published if t == "serre/z1/alerte"]
    assert len(alerts) == 1 and isinstance(alerts[0], Alert) and alerts[0].niveau == "warning"


def test_archive_purge_and_upload(tmp_path):
    archive = Archive(tmp_path / "a", retention_days=7)
    img = np.zeros((40, 40, 3), np.uint8)
    for days in (0, 3, 10):
        ts = T0 - timedelta(days=days)
        res = VisionResult(ts=ts, camera="cam-z1-a", image_id=f"cam-z1-a-{days}", modele="m",
                           detections=[{"bbox": None, "espece": "tomate", "espece_conf": 1,
                                        "sante": "sain", "sante_conf": 1, "classe": "c",
                                        "classe_conf": 1}],
                           score_anomalie=0, surface_verte_px=0)  # fmt: skip
        archive.save(img, res, {})
    assert archive.purge(T0) == 1 and len(list(archive.records())) == 2

    sent, fail = [], {"on": True}

    def send(payload):
        if fail["on"]:
            raise OSError("serveur injoignable")
        sent.append(payload)

    up = Uploader(archive, send)
    assert up.upload_pending() == 0 and len(list(archive.pending())) == 2
    fail["on"] = False
    assert up.upload_pending() == 2 and up.upload_pending() == 0
    assert "jpeg_b64" in sent[0] and sent[0]["resultat"]["camera"] == "cam-z1-a"


def test_folder_camera_and_config(tmp_path):
    import cv2

    (tmp_path / "imgs").mkdir()
    for i in range(2):
        cv2.imwrite(str(tmp_path / "imgs" / f"{i}.png"), np.full((10, 10, 3), i * 100, np.uint8))
    cam = open_camera(f"folder:{tmp_path / 'imgs'}")
    assert isinstance(cam, FolderCamera)
    first = cam.capture()
    cam.capture()
    assert (cam.capture() == first).all()  # cycles
    with pytest.raises(ValueError):
        open_camera("ftp:0")

    from edge.config import ROOT

    cfg = load_config(ROOT / "edge" / "config.yaml")  # the example of the repository is valid
    assert cfg.cameras[0].source.startswith("folder:") and cfg.modeles.backend == "onnx"
