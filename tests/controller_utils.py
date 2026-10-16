"""Helpers of the controller tests: the sample greenhouse and a state fed by hand."""

from datetime import UTC, datetime, timedelta

from common.mqtt import (
    ActuatorState,
    Detection,
    SensorReading,
    VisionResult,
    encode,
    sensor_topic,
    state_topic,
    vision_topic,
)
from edge.controller.config import load_greenhouse
from edge.controller.context import make_ctx
from edge.controller.state import GreenhouseState

# 2026-07-15 10:00 UTC = 12:00 Europe/Paris: daytime, inside the photoperiod.
NOON = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
NIGHT = datetime(2026, 7, 15, 1, 0, tzinfo=UTC)  # 03:00 local

UNITS = {
    "temperature": "°C",
    "humidite": "%",
    "ph": "pH",
    "ec": "mS/cm",
    "lux": "lx",
    "niveau_cuve": "%",
    "presence": "cibles",
    "humidite_sol": "%",
    "pression": "hPa",
}


def greenhouse():
    return load_greenhouse()


def reading(sensor, value, ts, node="esp32-01", qualite="ok", emplacement=None):
    return SensorReading(
        ts=ts,
        noeud=node,
        valeur=value,
        unite=UNITS.get(sensor, ""),
        qualite=qualite,
        emplacement=emplacement,
    )


def feed(state: GreenhouseState, zone, sensor, value, ts, **kw):
    state.on_message(sensor_topic(zone, sensor), encode(reading(sensor, value, ts, **kw)))


def set_actuator(state: GreenhouseState, zone, actuator, action, ts, valeur=None):
    state.on_message(
        state_topic(zone, actuator), encode(ActuatorState(ts=ts, action=action, valeur=valeur))
    )


def ctx(gh, state: GreenhouseState, zone, now):
    return make_ctx(gh, state.zone(zone), now)


def minutes(n: float) -> timedelta:
    return timedelta(minutes=n)


LEFT = (0.1, 0.2, 0.2, 0.2)  # inside the region of z1-A1 on cam-z1-a
RIGHT = (0.6, 0.2, 0.2, 0.2)  # z1-A2


def vision(ts, classe, camera="cam-z1-a", bbox=LEFT, conf=0.85, anomalie=None, px=50_000):
    """A VisionResult with one detection of `classe` ("tomate/maladie/mildiou")."""
    espece = classe.split("/")[0]
    sain = classe.endswith("/sain/sain")
    d = Detection(bbox=bbox, espece=espece, espece_conf=0.95, sante="sain" if sain else "anormal",
                  sante_conf=0.9, classe=classe, classe_conf=conf)  # fmt: skip
    return VisionResult(
        ts=ts,
        camera=camera,
        image_id=f"{camera}-{ts:%Y%m%dT%H%M%S}",
        modele="test-clf",
        detections=[d],
        score_anomalie=anomalie if anomalie is not None else (0.1 if sain else 0.6),
        surface_verte_px=px,
    )


def feed_vision(state: GreenhouseState, zone, result):
    state.on_message(vision_topic(zone, result.camera), encode(result))


def feed_captures(state: GreenhouseState, zone, classe, start, n=3, every=10, **kw):
    """n captures `every` minutes apart, the last one at `start + (n - 1) * every`."""
    for i in range(n):
        feed_vision(state, zone, vision(start + minutes(i * every), classe, **kw))
