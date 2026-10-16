"""From vision predictions to alerts (docs/05 §4): smoothing over N captures, humidity fusion."""

import json
from datetime import UTC, datetime, timedelta

from common.mqtt import SensorReading, VisionResult, encode, sensor_topic, vision_topic
from edge.controller.vision_alerts import (
    HumidityTracker,
    VisionAlertConfig,
    VisionAlerter,
    VisionSmoother,
    replay,
)

T0 = datetime(2026, 10, 12, 0, 0, tzinfo=UTC)


def result(i: int, sante="anormal", conf=0.9, classe="tomate/maladie/mildiou", cam="cam-z1-a"):
    return VisionResult(
        ts=T0 + timedelta(minutes=10 * i), camera=cam, image_id=f"{cam}-{i}", modele="m",
        detections=[{"bbox": None, "espece": "tomate", "espece_conf": 0.9, "sante": sante,
                     "sante_conf": conf, "classe": classe, "classe_conf": 0.8}],
        score_anomalie=0.0, surface_verte_px=100,
    )  # fmt: skip


def humidity(alerter, hours, value=90.0):
    r = SensorReading(ts=T0 + timedelta(hours=hours), noeud="esp32-01", valeur=value, unite="%",
                      qualite="ok")  # fmt: skip
    alerter.on_sensor("z1", "humidite", r)


def test_smoother_consecutive_and_mean():
    s = VisionSmoother(3, 0.6)
    assert s.update("c", 0.9) == (True, False)
    assert s.update("c", 0.9) == (True, False)
    assert s.update("c", 0.5) == (False, False)  # a reflection breaks the streak
    assert [s.update("c", 0.9)[1] for _ in range(3)] == [False, False, True]
    m = VisionSmoother(3, 0.6, "moyenne")
    assert [m.update("c", v)[1] for v in (0.9, 0.5, 0.7)] == [False, False, True]


def test_isolated_then_persistent_then_back_to_normal():
    a = VisionAlerter()
    levels = [a.on_vision("z1", result(i)) for i in range(4)]
    assert levels[0].niveau == "info" and levels[1] is None  # same level: no repeat
    assert levels[2].niveau == "warning" and levels[3] is None
    assert "mildiou" in levels[2].message
    back = a.on_vision("z1", result(4, sante="sain"))
    assert back.niveau == "info" and "normale" in back.message


def test_humidity_fusion_escalates_to_critique():
    a = VisionAlerter()
    humidity(a, -7)  # > 85 % for 7 h at the first capture
    alerts = [a.on_vision("z1", result(i)) for i in range(3)]
    assert alerts[2].niveau == "critique" and "humidité" in alerts[2].message

    b = VisionAlerter()  # disease not favoured by humidity: warning only
    humidity(b, -7)
    alerts = [b.on_vision("z1", result(i, classe="tomate/virus/mosaique")) for i in range(3)]
    assert alerts[2].niveau == "warning"

    c = VisionAlerter()  # humid for too short a time
    humidity(c, -2)
    assert [c.on_vision("z1", result(i)) for i in range(3)][2].niveau == "warning"


def test_humidity_tracker_resets():
    t = HumidityTracker(85)
    mk = lambda h, v, q="ok": SensorReading(ts=T0 + timedelta(hours=h), noeud="n", valeur=v,  # noqa: E731
                                            unite="%", qualite=q)  # fmt: skip
    t.update("z1", mk(0, 90))
    t.update("z1", mk(1, 92))
    assert t.duration("z1", T0 + timedelta(hours=3)) == timedelta(hours=3)
    t.update("z1", mk(4, 10, "erreur"))  # faulty reading ignored
    t.update("z1", mk(5, 80))
    assert t.duration("z1", T0 + timedelta(hours=6)) == timedelta(0)


def test_on_message_and_replay(tmp_path):
    a = VisionAlerter(VisionAlertConfig(n=2))
    hum = SensorReading(ts=T0 - timedelta(hours=7), noeud="n", valeur=95, unite="%", qualite="ok")
    assert a.on_message(sensor_topic("z1", "humidite"), encode(hum)) is None
    a.on_message(vision_topic("z1", "cam-z1-a"), encode(result(0)))
    topic, alert = a.on_message(vision_topic("z1", "cam-z1-a"), encode(result(1)))
    assert topic == "serre/z1/alerte" and alert.niveau == "critique"

    day = tmp_path / "2026-10-12"
    day.mkdir()
    for i in range(3):
        (day / f"r{i}.json").write_text(json.dumps({"resultat": result(i).model_dump(mode="json")}))
    assert [x.niveau for x in replay(VisionAlerter(), tmp_path, "z1")] == ["info", "warning"]


def test_out_of_taxonomy_camera_alerts_on_score_anomalie_only():
    a = VisionAlerter(vision_auto=lambda cam: False)
    for h in range(8):
        humidity(a, h)
    healthy = [result(i, sante="sain", conf=0.99) for i in range(3)]
    for r in healthy:  # the classifier health is not used: score_anomalie = 0
        assert a.on_vision("z1", r) is None
    weird = [
        result(i, sante="sain").model_copy(update={"score_anomalie": 0.9}) for i in range(3, 6)
    ]
    levels = [a.on_vision("z1", r) for r in weird]
    assert levels[0].niveau == "info" and levels[2].niveau == "warning"  # never critique
    assert "score d'anomalie" in levels[2].message and "mildiou" not in levels[2].message
