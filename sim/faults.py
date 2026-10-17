"""Injectable faults (docs/06 §5): frozen sensor, outlier, node disconnection.

CLI syntax (`python -m sim --panne …`), times in simulated minutes from the start:
    fige:z1/temperature@30-90        frozen value from minute 30 to 90
    aberrant:z1/humidite@60          one outlier at minute 60 (then every --periode)
    deconnexion:esp32-02@10-40       node silent and `offline` from 10 to 40 min
    cuve_vide:z2@120                 the tank of z2 drops to 0 % at minute 120
    valeur:z1/humidite=92@0-240      the sensor reads about 92 from minute 0 to 240
    maladie:z1-A1/tomate/maladie/mildiou@30-180
                                     the simulated camera sees this class on z1-A1
"""

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

Kind = Literal["fige", "aberrant", "deconnexion", "cuve_vide", "valeur", "maladie"]
_RE = re.compile(
    r"^(fige|aberrant|deconnexion|cuve_vide|valeur|maladie):([\w/=.-]+)"
    r"@(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))?$"
)


@dataclass
class Fault:
    kind: Kind
    target: str  # "z1/temperature", "esp32-02", "z2" or "z1-A1/tomate/maladie/mildiou"
    start: datetime
    end: datetime | None = None
    frozen: float | None = None  # fige: the frozen value; valeur: the forced one

    def active(self, t: datetime) -> bool:
        return t >= self.start and (self.end is None or t < self.end)

    @property
    def zone_sensor(self) -> tuple[str, str]:
        zone, _, sensor = self.target.partition("/")
        return zone, sensor.partition("=")[0]


def parse_fault(spec: str, t0: datetime) -> Fault:
    m = _RE.match(spec)
    if not m:
        raise ValueError(f"panne invalide {spec!r} (ex. fige:z1/temperature@30-90)")
    kind, target, start, end = m.groups()
    s = t0 + timedelta(minutes=float(start))
    e = t0 + timedelta(minutes=float(end)) if end else None
    if kind == "aberrant" and e is None:
        e = s + timedelta(seconds=1)  # one reading
    fault = Fault(kind, target, s, e)
    if kind == "valeur":
        _, eq, value = target.partition("=")
        if not eq:
            raise ValueError(f"panne invalide {spec!r} (ex. valeur:z1/humidite=92@0-240)")
        fault.frozen = float(value)
    elif kind == "maladie" and target.count("/") != 3:
        raise ValueError(f"panne invalide {spec!r} (ex. maladie:z1-A1/tomate/maladie/mildiou@30)")
    return fault


class Faults:
    def __init__(self, faults: list[Fault] = ()):
        self.faults = list(faults)

    def disconnected(self, node: str, t: datetime) -> bool:
        return any(
            f.kind == "deconnexion" and f.target == node and f.active(t) for f in self.faults
        )

    def tank_empty(self, zone: str, t: datetime) -> bool:
        return any(f.kind == "cuve_vide" and f.target == zone and f.active(t) for f in self.faults)

    def disease(self, emplacement: str, t: datetime) -> str | None:
        """Class the simulated camera sees on the emplacement (None: healthy)."""
        for f in self.faults:
            emp, _, classe = f.target.partition("/")
            if f.kind == "maladie" and emp == emplacement and f.active(t):
                return classe
        return None

    def apply(self, zone: str, sensor: str, value: float, t: datetime) -> float:
        for f in self.faults:
            if f.kind not in ("fige", "aberrant", "valeur") or f.zone_sensor != (zone, sensor):
                continue
            if f.kind == "valeur":
                if f.active(t):  # small jitter: a forced value is not a frozen sensor
                    return f.frozen + 0.3 * math.sin(t.timestamp() / 97)
                continue
            if not f.active(t):
                if f.kind == "fige" and f.end is not None and t >= f.end:
                    f.frozen = None
                continue
            if f.kind == "fige":
                if f.frozen is None:
                    f.frozen = value
                return f.frozen
            return value + (40.0 if value < 50 else -40.0)  # plausible-looking but wrong
        return value
