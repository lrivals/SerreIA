"""Injectable faults (docs/06 §5): frozen sensor, outlier, node disconnection.

CLI syntax (`python -m sim --panne …`), times in simulated minutes from the start:
    fige:z1/temperature@30-90        frozen value from minute 30 to 90
    aberrant:z1/humidite@60          one outlier at minute 60 (then every --periode)
    deconnexion:esp32-02@10-40       node silent and `offline` from 10 to 40 min
    cuve_vide:z2@120                 the tank of z2 drops to 0 % at minute 120
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

Kind = Literal["fige", "aberrant", "deconnexion", "cuve_vide"]
_RE = re.compile(
    r"^(fige|aberrant|deconnexion|cuve_vide):([\w/-]+)@(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))?$"
)


@dataclass
class Fault:
    kind: Kind
    target: str  # "z1/temperature", "esp32-02" or "z2"
    start: datetime
    end: datetime | None = None
    frozen: float | None = None

    def active(self, t: datetime) -> bool:
        return t >= self.start and (self.end is None or t < self.end)

    @property
    def zone_sensor(self) -> tuple[str, str]:
        zone, _, sensor = self.target.partition("/")
        return zone, sensor


def parse_fault(spec: str, t0: datetime) -> Fault:
    m = _RE.match(spec)
    if not m:
        raise ValueError(f"panne invalide {spec!r} (ex. fige:z1/temperature@30-90)")
    kind, target, start, end = m.groups()
    s = t0 + timedelta(minutes=float(start))
    e = t0 + timedelta(minutes=float(end)) if end else None
    if kind == "aberrant" and e is None:
        e = s + timedelta(seconds=1)  # one reading
    return Fault(kind, target, s, e)


class Faults:
    def __init__(self, faults: list[Fault] = ()):
        self.faults = list(faults)

    def disconnected(self, node: str, t: datetime) -> bool:
        return any(
            f.kind == "deconnexion" and f.target == node and f.active(t) for f in self.faults
        )

    def tank_empty(self, zone: str, t: datetime) -> bool:
        return any(f.kind == "cuve_vide" and f.target == zone and f.active(t) for f in self.faults)

    def apply(self, zone: str, sensor: str, value: float, t: datetime) -> float:
        for f in self.faults:
            if f.kind not in ("fige", "aberrant") or f.zone_sensor != (zone, sensor):
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
