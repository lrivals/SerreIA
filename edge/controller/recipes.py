"""Culture recipes and zone setpoints (docs/09 §6), `edge/controller/recettes.yaml`.

A recipe gives setpoints per species and growth stage. When a zone holds plants of
several recipes, the zone setpoint is the intersection of their ranges; when it is empty
the range of the plant marked `prioritaire` wins (the UI reports the incompatibility).
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

Range = tuple[float, float]


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DayNight(_Cfg):
    jour: Range
    nuit: Range


class StageSetpoints(_Cfg):
    temperature: DayNight
    humidite: Range
    co2_max: float | None = None
    photoperiode_h: float = Field(ge=0, le=24)
    dli_cible: float | None = None  # mol/m²/day
    ph: Range | None = None
    ec: Range | None = None  # mS/cm
    humidite_sol: Range | None = None  # %

    @model_validator(mode="after")
    def _ordered(self) -> "StageSetpoints":
        for name in ("humidite", "ph", "ec", "humidite_sol"):
            r = getattr(self, name)
            if r is not None and r[0] > r[1]:
                raise ValueError(f"{name}: min > max")
        return self


class Recipe(_Cfg):
    espece: str
    stades: dict[str, StageSetpoints] = Field(min_length=1)

    def stage(self, stade: str) -> StageSetpoints:
        try:
            return self.stades[stade]
        except KeyError:
            raise KeyError(
                f"stade {stade!r} absent de la recette ({', '.join(self.stades)})"
            ) from None


def load_recipes(path: Path) -> dict[str, Recipe]:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    return {name: Recipe.model_validate(r) for name, r in raw.items()}


def intersect(a: Range | None, b: Range | None) -> Range | None:
    """Intersection of two ranges; None when one is missing… or when it is empty."""
    if a is None:
        return b
    if b is None:
        return a
    lo, hi = max(a[0], b[0]), min(a[1], b[1])
    return (lo, hi) if lo <= hi else None


@dataclass(frozen=True)
class PlantStage:
    recette: str
    stade: str
    prioritaire: bool = False


@dataclass
class Setpoints:
    """Setpoints of a zone: what the rules compare the measurements with."""

    temperature_jour: Range
    temperature_nuit: Range
    humidite: Range
    photoperiode_h: float
    co2_max: float | None = None
    dli_cible: float | None = None
    ph: Range | None = None
    ec: Range | None = None
    humidite_sol: Range | None = None
    sources: list[str] = field(default_factory=list)  # "recette/stade"
    incompatibles: list[str] = field(default_factory=list)  # ranges with empty intersection

    def temperature(self, jour: bool) -> Range:
        return self.temperature_jour if jour else self.temperature_nuit

    def as_evidence(self) -> dict:
        """`consignes` field of a Decision (docs/10 §2)."""
        out = {
            "recettes": self.sources,
            "temperature": {"jour": self.temperature_jour, "nuit": self.temperature_nuit},
            "humidite": self.humidite,
        }
        for name in ("ph", "ec", "humidite_sol", "dli_cible", "co2_max"):
            if getattr(self, name) is not None:
                out[name] = getattr(self, name)
        out["photoperiode_h"] = self.photoperiode_h
        return out


_RANGES = ("humidite", "ph", "ec", "humidite_sol")


def zone_setpoints(
    plants: list[PlantStage], recipes: dict[str, Recipe], hydro: bool = True
) -> Setpoints | None:
    """Intersection of the recipes of the plants of a zone; None for an empty zone.
    pH and EC only make sense in a hydro zone: they are dropped otherwise."""
    if not plants:
        return None
    stages = [(p, recipes[p.recette].stage(p.stade)) for p in plants]
    prio = next((s for p, s in stages if p.prioritaire), stages[0][1])
    sp = Setpoints(
        temperature_jour=prio.temperature.jour,
        temperature_nuit=prio.temperature.nuit,
        humidite=prio.humidite,
        photoperiode_h=prio.photoperiode_h,
        co2_max=prio.co2_max,
        dli_cible=prio.dli_cible,
        ph=prio.ph,
        ec=prio.ec,
        humidite_sol=prio.humidite_sol,
        sources=[f"{p.recette}/{p.stade}" for p, _ in stages],
    )

    def merge(name: str, values: list[Range | None], fallback: Range | None) -> Range | None:
        acc: Range | None = None
        for v in values:
            if v is None:
                continue
            nxt = intersect(acc, v)
            if nxt is None:
                sp.incompatibles.append(name)
                return fallback
            acc = nxt
        return acc

    sp.temperature_jour = merge(
        "temperature_jour", [s.temperature.jour for _, s in stages], prio.temperature.jour
    )
    sp.temperature_nuit = merge(
        "temperature_nuit", [s.temperature.nuit for _, s in stages], prio.temperature.nuit
    )
    for name in _RANGES if hydro else ("humidite", "humidite_sol"):
        setattr(sp, name, merge(name, [getattr(s, name) for _, s in stages], getattr(prio, name)))
    if not hydro:
        sp.ph = sp.ec = None
    caps = [s.co2_max for _, s in stages if s.co2_max is not None]
    sp.co2_max = min(caps) if caps else None
    return sp
