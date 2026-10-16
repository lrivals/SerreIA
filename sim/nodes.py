"""Emulated ESP32 nodes (docs/06 §1.3, §3): same topics, payloads and local logic as the
firmware, so the controller cannot tell the simulator from the real greenhouse.

- sensor nodes: a reading every 30 s, sensor noise, physical range → `qualite`;
- radar (in the air node): `presence` on every change and every 30 s;
- actuator node: `serre/<zone>/cmd/#` → `etat/` (retained) on change; pump commands
  without `duree_s` or beyond the firmware maximum are refused; pumps cut at the deadline
  and forbidden when the tank is empty (local float switch, independent of the Pi).
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

from common.mqtt import (
    PHYSICAL_RANGE,
    Actuator,
    ActuatorState,
    Command,
    SensorReading,
    SensorType,
    decode,
    parse_topic,
    quality,
    sensor_topic,
    state_topic,
)

from .faults import Faults

log = logging.getLogger(__name__)

PERIOD_S = 30.0
NOISE = {
    SensorType.TEMPERATURE: 0.1,
    SensorType.HUMIDITE: 0.8,
    SensorType.CO2: 10.0,
    SensorType.LUX: 0.02,
    SensorType.PRESSION: 0.1,
    SensorType.PH: 0.01,
    SensorType.EC: 0.01,
    SensorType.TEMP_EAU: 0.1,
    SensorType.NIVEAU_CUVE: 0.5,
    SensorType.HUMIDITE_SOL: 0.5,
    SensorType.PRESENCE: 0.0,
}
RELATIVE = {SensorType.LUX}
CLAMPED = {
    SensorType.HUMIDITE,
    SensorType.HUMIDITE_SOL,
    SensorType.NIVEAU_CUVE,
    SensorType.LUX,
    SensorType.CO2,
}
FLOAT_SWITCH_MIN = 5.0  # % : the float switch of the actuator node opens below
PUMP_MAX_S = 1800.0  # firmware limit (MAX_PUMP_S in firmware/include/node_config.h)
DIGITS = {SensorType.PH: 2, SensorType.EC: 2, SensorType.PRESENCE: 0}


@dataclass
class SensorNode:
    id: str
    zone: str
    sensors: list[tuple[SensorType, str | None]]
    period_s: float = PERIOD_S
    radar: bool = False
    rng: np.random.Generator = field(default_factory=lambda: np.random.default_rng(0))
    _next: datetime | None = None
    _presence: float | None = None

    def poll(self, t: datetime, truth: dict, faults: Faults) -> list[tuple[str, SensorReading]]:
        if faults.disconnected(self.id, t):
            self._next = None
            return []
        out = []
        due = self._next is None or t >= self._next
        if due:
            self._next = t + timedelta(seconds=self.period_s)
        for sensor, emp in self.sensors:
            if (sensor, emp) not in truth:
                continue
            value = truth[(sensor, emp)]
            if sensor == SensorType.PRESENCE:
                if not due and value == self._presence:
                    continue
                self._presence = value
            elif not due:
                continue
            out.append(
                (sensor_topic(self.zone, sensor), self.reading(t, sensor, emp, value, faults))
            )
        return out

    def reading(self, t, sensor, emp, value, faults: Faults) -> SensorReading:
        rng = PHYSICAL_RANGE[sensor]
        sigma = NOISE[sensor] * (abs(value) if sensor in RELATIVE else 1.0)
        v = value + sigma * self.rng.standard_normal()
        if sensor in CLAMPED:  # a saturated sensor reads its bound, noise does not leave it
            v = min(rng.max, max(rng.min, v))
        v = round(faults.apply(self.zone, sensor, v, t), DIGITS.get(sensor, 1))
        return SensorReading(
            ts=t,
            noeud=self.id,
            valeur=v,
            unite=rng.unite,
            qualite=quality(sensor, v),
            emplacement=emp,
        )


@dataclass
class _Running:
    state: ActuatorState
    until: datetime | None = None


class ActuatorNode:
    """Actuators of several zones on one node (esp32-04)."""

    def __init__(self, id: str, zones: dict[str, list[Actuator]], pump_max_s: float = PUMP_MAX_S):
        self.id, self.zones, self.pump_max_s = id, zones, pump_max_s
        self.running: dict[tuple[str, Actuator], _Running] = {}
        self.outbox: list[tuple[str, ActuatorState]] = []
        self.refused: list[tuple[str, str]] = []
        self.tank: dict[str, float] = {}  # zone -> tank level seen by the local float switch

    def topics(self) -> list[str]:
        return [f"serre/{z}/cmd/#" for z in self.zones]

    def level(self, zone: str, actuator: Actuator) -> float:
        r = self.running.get((zone, actuator))
        if r is None or r.state.action == "off":
            return 0.0
        return 1.0 if r.state.action == "on" else (r.state.valeur or 0) / 100

    def levels(self, zone: str) -> dict[str, float]:
        return {a: self.level(zone, a) for a in self.zones.get(zone, [])}

    def _set(self, zone: str, a: Actuator, state: ActuatorState, until: datetime | None) -> None:
        prev = self.running.get((zone, a))
        self.running[(zone, a)] = _Running(state, until)
        if prev is None or (prev.state.action, prev.state.valeur) != (state.action, state.valeur):
            self.outbox.append((state_topic(zone, a), state))

    def start(self, t: datetime) -> None:
        """Boot: every actuator off (retained etat/)."""
        for zone, acts in self.zones.items():
            for a in acts:
                self._set(zone, a, ActuatorState(ts=t, action="off"), None)

    def on_command(self, topic: str, payload: bytes, t: datetime) -> None:
        parsed = parse_topic(topic)
        if parsed.subject == "capture":
            return
        zone, a = parsed.scope, Actuator(parsed.subject)
        if a not in self.zones.get(zone, []):
            return
        try:
            cmd: Command = decode(topic, payload)
        except ValueError as e:  # e.g. a pump without duree_s: refused, as the firmware does
            self.refused.append((topic, str(e)))
            log.warning("%s : commande refusée %s (%s)", self.id, topic, e)
            return
        if cmd.action == "off":
            self._set(zone, a, ActuatorState(ts=t, action="off"), None)
            return
        if a.is_pump:
            if cmd.duree_s > self.pump_max_s:
                self.refused.append((topic, f"duree_s > {self.pump_max_s:g}"))
                return
            if self.tank.get(zone, 100.0) < FLOAT_SWITCH_MIN:
                self.refused.append((topic, "cuve vide"))
                return
        until = t + timedelta(seconds=cmd.duree_s) if cmd.duree_s else None
        self._set(zone, a, ActuatorState(ts=t, action=cmd.action, valeur=cmd.valeur), until)

    def step(self, t: datetime) -> None:
        for (zone, a), r in list(self.running.items()):
            if r.state.action == "off":
                continue
            empty = a.is_pump and self.tank.get(zone, 100.0) < FLOAT_SWITCH_MIN
            if (r.until is not None and t >= r.until) or empty:
                self._set(zone, a, ActuatorState(ts=t, action="off"), None)

    def drain(self) -> list[tuple[str, ActuatorState]]:
        out, self.outbox = self.outbox, []
        return out
