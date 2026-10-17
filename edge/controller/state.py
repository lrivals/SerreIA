"""What the controller knows of the greenhouse, built from the MQTT stream.

Latest readings (per emplacement for soil probes), real actuator states (`etat/`,
retained), node status, recent vision results and the rolling aggregates the rules use:
time above a humidity threshold, 12 h mean temperature, natural DLI of the day…
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from common.mqtt import (
    ActuatorState,
    SensorReading,
    SensorType,
    TopicKind,
    VisionResult,
    decode,
    parse_topic,
)

HISTORY = timedelta(hours=26)  # forecast window (24 h) + margin
VISION_HISTORY = timedelta(hours=48)
Key = tuple[str, str | None]  # (sensor type, emplacement)


@dataclass
class Spell:
    """Start of the current spell above a threshold (humidity, leaf wetness)."""

    seuil: float
    since: datetime | None = None

    def update(self, reading: SensorReading) -> None:
        if reading.qualite == "erreur":
            return
        if reading.valeur > self.seuil:
            if self.since is None:
                self.since = reading.ts
        else:
            self.since = None

    def hours(self, now: datetime) -> float:
        return (now - self.since).total_seconds() / 3600 if self.since else 0.0


@dataclass
class Pending:
    """Last command sent to an actuator, until `etat/` confirms it."""

    action: str
    valeur: float | None
    ts: datetime


@dataclass
class ZoneState:
    zone: str
    readings: dict[Key, SensorReading] = field(default_factory=dict)
    history: dict[str, deque[tuple[datetime, float]]] = field(default_factory=dict)
    actuators: dict[str, ActuatorState] = field(default_factory=dict)
    pending: dict[str, Pending] = field(default_factory=dict)
    last_on: dict[str, datetime] = field(default_factory=dict)  # last "on" sent per actuator
    owner: dict[str, str] = field(default_factory=dict)  # rule that switched an actuator on
    rule_fired: dict[str, datetime] = field(default_factory=dict)  # last decision per rule id
    # Temporary setpoint changes decided by a rule: name -> (delta, until), docs/10 §5.
    consignes: dict[str, tuple[float, datetime]] = field(default_factory=dict)
    vision: deque[VisionResult] = field(default_factory=deque)
    spells: dict[float, Spell] = field(default_factory=dict)  # humidity threshold -> spell
    dli: float = 0.0  # mol/m², measured light of the current local day
    dli_day: object = None
    _last_lux: tuple[datetime, float] | None = None

    # --- updates ------------------------------------------------------------------------

    def on_reading(
        self, sensor: str, r: SensorReading, lux_to_ppfd: float = 0.0185, tz=None
    ) -> None:
        self.readings[(sensor, r.emplacement)] = r
        if r.qualite == "erreur":
            return
        h = self.history.setdefault(sensor, deque())
        h.append((r.ts, r.valeur))
        while h and r.ts - h[0][0] > HISTORY:
            h.popleft()
        if sensor == SensorType.HUMIDITE:
            for spell in self.spells.values():
                spell.update(r)
        if sensor == SensorType.LUX:
            self._integrate_light(r, lux_to_ppfd, tz)

    def _integrate_light(self, r: SensorReading, k: float, tz) -> None:
        day = r.ts.astimezone(tz).date() if tz else r.ts.date()
        if day != self.dli_day:
            self.dli_day, self.dli, self._last_lux = day, 0.0, None
        if self._last_lux is not None:
            t0, lux0 = self._last_lux
            dt = (r.ts - t0).total_seconds()
            if 0 < dt <= 1800:  # ignore gaps: a dead sensor must not count as daylight
                self.dli += k * (lux0 + r.valeur) / 2 * dt / 1e6
        self._last_lux = (r.ts, r.valeur)

    def on_state(self, actuator: str, s: ActuatorState) -> None:
        self.actuators[actuator] = s
        h = self.history.setdefault(f"etat_{actuator}", deque())  # forecast input
        h.append((s.ts, self.actuator_level(actuator)))
        while h and s.ts - h[0][0] > HISTORY:
            h.popleft()
        p = self.pending.get(actuator)
        if p is not None and p.action == s.action and p.valeur == s.valeur:
            del self.pending[actuator]
        if s.action == "off":
            self.owner.pop(actuator, None)

    def on_vision(self, r: VisionResult) -> None:
        self.vision.append(r)
        while self.vision and r.ts - self.vision[0].ts > VISION_HISTORY:
            self.vision.popleft()

    # --- queries ------------------------------------------------------------------------

    def value(
        self,
        sensor: str,
        now: datetime | None = None,
        max_age: timedelta | None = None,
        emplacement: str | None = None,
    ) -> float | None:
        """Latest usable value (not `erreur`, not older than max_age)."""
        r = self.readings.get((sensor, emplacement))
        if r is None or r.qualite == "erreur":
            return None
        if now is not None and max_age is not None and now - r.ts > max_age:
            return None
        return r.valeur

    def reading(self, sensor: str, emplacement: str | None = None) -> SensorReading | None:
        return self.readings.get((sensor, emplacement))

    def emplacements(self, sensor: str) -> list[str]:
        return sorted(e for s, e in self.readings if s == sensor and e is not None)

    def recent(self, sensor: str, now: datetime, window: timedelta) -> list[float]:
        """Values of the last `window` (latest first); the history is in time order, so
        only its end is read (this runs at every tick)."""
        out = []
        for t, v in reversed(self.history.get(sensor, ())):
            if now - t > window:
                break
            out.append(v)
        return out

    def mean(self, sensor: str, now: datetime, window: timedelta) -> float | None:
        values = self.recent(sensor, now, window)
        return sum(values) / len(values) if values else None

    def spell(self, seuil: float) -> Spell:
        """Spell above `seuil` % humidity; created on first use and fed from the history."""
        if seuil not in self.spells:
            sp = self.spells[seuil] = Spell(seuil)
            for t, v in self.history.get(SensorType.HUMIDITE, ()):
                sp.since = (sp.since or t) if v > seuil else None
        return self.spells[seuil]

    def actuator_on(self, actuator: str) -> bool:
        s = self.actuators.get(actuator)
        return s is not None and s.action != "off"

    def actuator_level(self, actuator: str) -> float:
        """0..1 (on = 1, pwm = valeur / 100), for energy and forecast inputs."""
        s = self.actuators.get(actuator)
        if s is None or s.action == "off":
            return 0.0
        return 1.0 if s.action == "on" else (s.valeur or 0.0) / 100


@dataclass
class GreenhouseState:
    zones: dict[str, ZoneState] = field(default_factory=dict)
    nodes: dict[str, str] = field(default_factory=dict)  # node -> online | offline
    node_seen: dict[str, datetime] = field(default_factory=dict)
    lux_to_ppfd: float = 0.0185
    tz: object = None

    def zone(self, zone: str) -> ZoneState:
        return self.zones.setdefault(zone, ZoneState(zone))

    def on_message(self, topic: str, payload: bytes | str):
        """Update from a contract message; returns (parsed topic, message)."""
        parsed = parse_topic(topic)
        message = decode(topic, payload)
        match parsed.kind:
            case TopicKind.CAPTEUR:
                self.zone(parsed.scope).on_reading(
                    parsed.subject, message, self.lux_to_ppfd, self.tz
                )
                self.node_seen[message.noeud] = message.ts
            case TopicKind.ETAT:
                self.zone(parsed.scope).on_state(parsed.subject, message)
            case TopicKind.VISION:
                self.zone(parsed.scope).on_vision(message)
            case TopicKind.STATUS:
                self.nodes[parsed.scope] = message
        return parsed, message
