"""Helpers of the controller tests: the sample greenhouse and a state fed by hand."""

from datetime import UTC, datetime, timedelta

from common.mqtt import ActuatorState, SensorReading, encode, sensor_topic, state_topic
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
