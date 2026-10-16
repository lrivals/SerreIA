"""Evaluation context of a zone at one controller tick, shared by every level."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from common.mqtt import Actuator, SensorReading

from .config import ActionneurCfg, Greenhouse, ZoneCfg
from .recipes import Setpoints
from .state import ZoneState


@dataclass
class Ctx:
    gh: Greenhouse
    zcfg: ZoneCfg
    zs: ZoneState
    sp: Setpoints | None
    now: datetime  # UTC
    local: datetime  # local time (photoperiod, presence ranges)
    jour: bool  # inside the photoperiod window of the zone

    @property
    def zone(self) -> str:
        return self.zcfg.id

    @property
    def max_age(self) -> timedelta:
        return timedelta(seconds=self.gh.cfg.securite.capteur_muet_s)

    def value(self, sensor: str, emplacement: str | None = None) -> float | None:
        """Fresh usable value: older than the 'sensor muted' delay counts as missing."""
        return self.zs.value(sensor, self.now, self.max_age, emplacement)

    def reading(self, sensor: str, emplacement: str | None = None) -> SensorReading | None:
        return self.zs.reading(sensor, emplacement)

    def act(self, actuator: Actuator) -> ActionneurCfg | None:
        return self.gh.cfg.actuator(self.zone, actuator)

    def since_on(self, actuator: str) -> float:
        """Seconds since the last "on" sent to the actuator (inf when never)."""
        t = self.zs.last_on.get(actuator)
        return (self.now - t).total_seconds() if t else float("inf")

    def window(self) -> tuple[datetime, datetime]:
        """Photoperiod window (local) of the current or next day."""
        h = self.sp.photoperiode_h if self.sp else 0.0
        start = self.local.replace(
            hour=self.zcfg.jour_debut.hour,
            minute=self.zcfg.jour_debut.minute,
            second=0,
            microsecond=0,
        )
        end = start + timedelta(hours=h)
        if self.local < start and self.local - (start - timedelta(days=1)) < timedelta(hours=h):
            start -= timedelta(days=1)  # photoperiod over midnight
            end -= timedelta(days=1)
        return start, end


def make_ctx(gh: Greenhouse, zs: ZoneState, now: datetime) -> Ctx:
    zcfg = gh.cfg.zone(zs.zone)
    local = now.astimezone(ZoneInfo(gh.cfg.fuseau))
    sp = gh.setpoints.get(zcfg.id)
    ctx = Ctx(gh, zcfg, zs, sp, now, local, False)
    start, end = ctx.window()
    ctx.jour = sp is not None and start <= local < end
    return ctx
