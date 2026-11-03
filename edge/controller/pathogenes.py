"""Disease risk parameters per pathogen and crop (docs/22 L5, L7), `pathogenes.yaml`.

Mildew: one block per species, `defaut` for the others. A block without values falls back
to the historical thresholds of `serre.yaml` (`risque.humectation_h`, `t_min`, `t_max`),
which no source supports (`force: non_source`). Only a block with an `incubation` table
gives a date of expected symptoms (two-stage model of `2022-liu#004.0`).
"""

import bisect
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)

Range = tuple[float, float]
Force = Literal["essai", "revue", "guide", "commercial", "deduit", "non_source"]


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _Sourced(_Cfg):
    force: Force = "non_source"
    sources: list[str] = Field(default_factory=list)
    note: str | None = None


class Incubation(_Cfg):
    taux_h: dict[float, float] = Field(min_length=1)  # °C -> progress per hour

    def rate(self, t: float) -> float:
        """Rate at t °C: linear between the points of the table, constant outside."""
        pts = sorted(self.taux_h.items())
        xs = [x for x, _ in pts]
        i = bisect.bisect_left(xs, t)
        if i == 0:
            return pts[0][1]
        if i == len(pts):
            return pts[-1][1]
        (x0, y0), (x1, y1) = pts[i - 1], pts[i]
        return y0 + (y1 - y0) * (t - x0) / (x1 - x0)


class MildiouCfg(_Sourced):
    lwd_min_h: float | None = Field(default=None, gt=0)
    t_humectation: Range | None = None
    degres_heures_min: float | None = None
    incubation: Incubation | None = None


class BotrytisCfg(_Sourced):
    t: Range = (15.0, 22.0)
    hr_min: float = 90.0
    vpd_max: float = 0.5
    ecart_rosee_max: float = 1.0
    fenetre_fin_nuit_h: float = 2.0
    chauffage_s: float = 900.0
    ventilation_s: float = 900.0


class OidiumCfg(_Sourced):
    hr: Range = (60.0, 80.0)
    t: Range = (20.0, 28.0)
    amplitude_hr_24h: float = 20.0


class PathogenesCfg(_Cfg):
    mildiou: dict[str, MildiouCfg] = Field(default_factory=lambda: {"defaut": MildiouCfg()})
    botrytis: BotrytisCfg = Field(default_factory=BotrytisCfg)
    oidium: OidiumCfg = Field(default_factory=OidiumCfg)

    def mildew(self, espece: str, risque) -> "MildewParams":
        """Effective mildew parameters of a species (`risque`: RisqueCfg, the fallback)."""
        block = self.mildiou.get(espece) or self.mildiou.get("defaut") or MildiouCfg()
        t = block.t_humectation or (risque.t_min, risque.t_max)
        return MildewParams(
            espece=espece if espece in self.mildiou else "defaut",
            lwd_min_h=block.lwd_min_h or risque.humectation_h,
            t_humectation=(float(t[0]), float(t[1])),
            degres_heures_min=block.degres_heures_min,
            incubation=block.incubation,
            force=block.force,
            sources=list(block.sources),
        )


@dataclass(frozen=True)
class MildewParams:
    espece: str  # the block used: a species or "defaut"
    lwd_min_h: float
    t_humectation: Range
    degres_heures_min: float | None
    incubation: Incubation | None
    force: str
    sources: list[str]

    def infected(self, lwd_h: float, t_lwd: float | None) -> bool:
        """Infection criterion: wet long enough, at a suitable T° during the wetness, and
        enough degree-hours (LWD × TLWD) when the block requires them."""
        if t_lwd is None or lwd_h < self.lwd_min_h:
            return False
        lo, hi = self.t_humectation
        if not lo <= t_lwd <= hi:
            return False
        return self.degres_heures_min is None or lwd_h * t_lwd >= self.degres_heures_min


def load_pathogenes(path: Path) -> PathogenesCfg:
    if not path.exists():
        log.warning("%s absent : paramètres de risque maladie par défaut", path)
        return PathogenesCfg()
    return PathogenesCfg.model_validate(yaml.safe_load(path.read_text()) or {})
