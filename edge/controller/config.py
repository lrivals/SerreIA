"""Greenhouse configuration exported by the UI to the Pi (docs/09 §8), `serre.yaml`.

Zones, emplacements and active plants (species, recipe, stage), actuators with their
limits, safety limits. The controller reloads the file when it changes and records its
`config_version` in every decision, which makes decisions replayable.
"""

import logging
from datetime import time
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from common.mqtt import Actuator

from .recipes import PlantStage, Recipe, Setpoints, load_recipes, zone_setpoints

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = Path(__file__).with_name("serre.yaml")

ModeCulture = Literal["terre", "substrat", "hydro_nft", "hydro_dwc", "ebb_flow", "aeroponie"]
HYDRO = ("hydro_nft", "hydro_dwc", "ebb_flow", "aeroponie")


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PlanteCfg(_Cfg):
    id: str
    espece: str
    recette: str
    stade: str
    prioritaire: bool = False


class EmplacementCfg(_Cfg):
    id: str
    mode_culture: ModeCulture
    plante: PlanteCfg | None = None


class PlageCfg(_Cfg):
    debut: time
    fin: time

    def contains(self, t: time) -> bool:
        if self.debut <= self.fin:
            return self.debut <= t < self.fin
        return t >= self.debut or t < self.fin  # over midnight


class ZoneCfg(_Cfg):
    id: str = Field(pattern=r"^z\d+$")
    nom: str = ""
    emplacements: list[EmplacementCfg] = Field(default_factory=list)
    jour_debut: time = time(6, 0)  # start of the photoperiod (local time)
    presence_autorisee: list[PlageCfg] = Field(
        default_factory=lambda: [PlageCfg(debut=time(7, 0), fin=time(21, 0))]
    )
    cuve: bool = False  # the zone pumps from a tank with a niveau_cuve sensor

    @property
    def hydro(self) -> bool:
        return any(e.mode_culture in HYDRO for e in self.emplacements)

    @property
    def plants(self) -> list[PlanteCfg]:
        return [e.plante for e in self.emplacements if e.plante is not None]


class ActionneurCfg(_Cfg):
    id: str
    zone: str
    type: Actuator
    noeud: str = "esp32-04"
    commande: Literal["on_off", "pwm"] = "on_off"
    duree_max_s: float | None = None  # pumps: must be <= the firmware limit
    duree_s: float | None = None  # duration of a routine "on" (watering, misting)
    impulsion_s: float | None = None  # dosing pumps: one pulse
    melange_s: float = 600.0  # dosing pumps: wait before re-measuring
    delai_min_s: float = 0.0  # minimal time between two "on"
    marche_min_s: float = 300.0  # regulation: minimal "on" time (no short cycles)
    puissance_w: float | None = None
    ppfd_max: float | None = None  # LED: µmol/m²/s at canopy level, 100 %
    debit_l_h: float | None = None  # pumps: flow, base of the water estimate (docs/09 §5)

    @model_validator(mode="after")
    def _pump_bounded(self) -> "ActionneurCfg":
        if self.type.is_pump and self.duree_max_s is None:
            raise ValueError(f"{self.id}: duree_max_s est obligatoire pour une pompe")
        return self


class HysteresisCfg(_Cfg):
    temperature: float = 1.0  # °C
    humidite: float = 5.0  # %
    humidite_sol: float = 5.0  # %


class SecuriteCfg(_Cfg):
    t_max: float = 35.0
    t_min: float = 5.0
    ph_min: float = 4.5
    ph_max: float = 8.0
    niveau_cuve_min: float = 10.0  # %
    capteur_muet_s: float = 300.0
    capteur_fige_s: float = 1800.0


class RisqueCfg(_Cfg):
    hr_humectation: float = 90.0  # % above which the leaves are assumed wet
    humectation_h: float = 10.0
    t_min: float = 10.0
    t_max: float = 25.0
    ventilation_s: float = 900.0
    periode_s: float = 3600.0  # preventive ventilation at most once per period


class LumiereCfg(_Cfg):
    lux_vers_ppfd: float = 0.0185  # indicative daylight factor (docs/09 §5)
    pwm_complement: float = 100.0
    maintien_s: float = 1800.0  # minimal time between two complement decisions


class PrevisionCfg(_Cfg):
    modele: Path | None = Path("edge/models/forecast")  # missing directory: level 2 disabled
    hr_max_nuit: float = 85.0
    ventilation_s: float = 900.0
    ecart_sigma: float = 4.0  # anomaly when |measure - forecast| > k sigma


class SerreCfg(_Cfg):
    config_version: int = Field(ge=0)
    nom: str = "serre"
    fuseau: str = "Europe/Paris"
    tarif_kwh: float | None = None  # €/kWh, cost of the estimated consumption (docs/09 §5)
    recettes: Path = Path("edge/controller/recettes.yaml")
    zones: list[ZoneCfg] = Field(min_length=1)
    actionneurs: list[ActionneurCfg] = Field(default_factory=list)
    hysteresis: HysteresisCfg = Field(default_factory=HysteresisCfg)
    securite: SecuriteCfg = Field(default_factory=SecuriteCfg)
    risque: RisqueCfg = Field(default_factory=RisqueCfg)
    lumiere: LumiereCfg = Field(default_factory=LumiereCfg)
    prevision: PrevisionCfg = Field(default_factory=PrevisionCfg)

    @model_validator(mode="after")
    def _check(self) -> "SerreCfg":
        zones = {z.id for z in self.zones}
        seen = set()
        for a in self.actionneurs:
            if a.zone not in zones:
                raise ValueError(f"{a.id}: zone inconnue {a.zone}")
            if (a.zone, a.type) in seen:
                raise ValueError(f"{a.id}: un seul {a.type} par zone (topic cmd/{a.type})")
            seen.add((a.zone, a.type))
        return self

    def zone(self, zone: str) -> ZoneCfg:
        return next(z for z in self.zones if z.id == zone)

    def actuator(self, zone: str, actuator: Actuator | str) -> ActionneurCfg | None:
        return next((a for a in self.actionneurs if a.zone == zone and a.type == actuator), None)

    def resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else ROOT / path


class Greenhouse:
    """Loaded configuration + recipes, with the setpoints of each zone."""

    def __init__(self, cfg: SerreCfg, recipes: dict[str, Recipe]):
        self.cfg, self.recipes = cfg, recipes
        for z in cfg.zones:
            for p in z.plants:
                if p.recette not in recipes:
                    raise ValueError(f"plante {p.id}: recette inconnue {p.recette}")
                recipes[p.recette].stage(p.stade)
        self.setpoints: dict[str, Setpoints | None] = {
            z.id: zone_setpoints(
                [PlantStage(p.recette, p.stade, p.prioritaire) for p in z.plants], recipes, z.hydro
            )
            for z in cfg.zones
        }
        for zone, sp in self.setpoints.items():
            if sp is not None and sp.incompatibles:
                log.warning("plantes incompatibles dans %s : %s", zone, ", ".join(sp.incompatibles))

    @property
    def version(self) -> int:
        return self.cfg.config_version

    def emplacement_setpoints(self, zone: str, emplacement: str) -> Setpoints | None:
        """Setpoints of the plant of one emplacement (soil moisture is per emplacement)."""
        e = next((e for e in self.cfg.zone(zone).emplacements if e.id == emplacement), None)
        if e is None or e.plante is None:
            return self.setpoints.get(zone)
        p = e.plante
        return zone_setpoints([PlantStage(p.recette, p.stade)], self.recipes, False)


def load_greenhouse(path: Path = DEFAULT_CONFIG) -> Greenhouse:
    cfg = SerreCfg.model_validate(yaml.safe_load(Path(path).read_text()))
    return Greenhouse(cfg, load_recipes(cfg.resolve(cfg.recettes)))


class ConfigWatcher:
    """Hot reload: `get()` reloads the file when its mtime changed; a broken file keeps the
    previous configuration (logged)."""

    def __init__(self, path: Path = DEFAULT_CONFIG):
        self.path = Path(path)
        self.mtime = self.path.stat().st_mtime
        self.greenhouse = load_greenhouse(self.path)
        log.info("configuration v%d chargée (%s)", self.greenhouse.version, self.path)

    def get(self) -> Greenhouse:
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return self.greenhouse
        if mtime != self.mtime:
            self.mtime = mtime
            try:
                self.greenhouse = load_greenhouse(self.path)
                log.info("configuration v%d rechargée", self.greenhouse.version)
            except (OSError, ValueError, KeyError, yaml.YAMLError):
                log.exception(
                    "configuration invalide, version %d conservée", self.greenhouse.version
                )
        return self.greenhouse
