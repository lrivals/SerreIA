"""Greenhouse configuration exported by the UI to the Pi (docs/09 §8), `serre.yaml`.

Zones, emplacements and active plants (species, recipe, stage), actuators with their
limits, safety limits. The controller reloads the file when it changes and records its
`config_version` in every decision, which makes decisions replayable.

Besides what the controller uses, the file describes the whole greenhouse model of
docs/09 (containers, declared sensors, cameras and their regions, tanks): the seed loads
it into the database and `backend/config/export.py` writes it back.
"""

import logging
from datetime import date, time
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from common.mqtt import Actuator, SensorType

from .recipes import PlantStage, Recipe, Setpoints, load_recipes, zone_setpoints

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = Path(__file__).with_name("serre.yaml")

ModeCulture = Literal["terre", "substrat", "hydro_nft", "hydro_dwc", "ebb_flow", "aeroponie"]
HYDRO = ("hydro_nft", "hydro_dwc", "ebb_flow", "aeroponie")


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def capteur_id(noeud: str, sensor: str, emplacement: str | None = None) -> str:
    """Id of a measurement channel (node × type × emplacement), as the ingestion sees it."""
    return f"{noeud}-{sensor}" + (f"-{emplacement}" if emplacement else "")


class PlanteCfg(_Cfg):
    id: str
    espece: str  # key of vision/datasets/taxonomy.yaml, or any other species
    recette: str
    stade: str
    prioritaire: bool = False
    variete: str | None = None
    date_semis: date | None = None
    date_plantation: date | None = None
    notes: str | None = None


class ContenantCfg(_Cfg):
    type: Literal[
        "pot", "jardiniere", "sac_de_culture", "godet", "canal_NFT", "bac_DWC", "pleine_terre"
    ]
    volume_l: float | None = None
    materiau: str | None = None  # plastique, terre_cuite, geotextile
    drainage: bool | None = None


class EmplacementCfg(_Cfg):
    id: str
    mode_culture: ModeCulture
    plante: PlanteCfg | None = None
    contenant: ContenantCfg | None = None


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
    cuve: bool | str = False  # the zone pumps from a tank (true: its own, str: a shared one)

    @property
    def cuve_id(self) -> str | None:
        if isinstance(self.cuve, str):
            return self.cuve
        return f"cuve-{self.id}" if self.cuve else None

    @property
    def hydro(self) -> bool:
        return any(e.mode_culture in HYDRO for e in self.emplacements)

    @property
    def modes(self) -> set[str]:
        return {e.mode_culture for e in self.emplacements}

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
    debit_ml_min: float | None = None  # dosing pumps: flow, base of the inputs estimate

    @model_validator(mode="after")
    def _pump_bounded(self) -> "ActionneurCfg":
        if self.type.is_pump and self.duree_max_s is None:
            raise ValueError(f"{self.id}: duree_max_s est obligatoire pour une pompe")
        return self


class CuveCfg(_Cfg):
    id: str
    volume_l: float | None = None


class CapteurCfg(_Cfg):
    """A sensor device: one channel per measured type (an SHT41 gives temperature and
    humidite). `emplacements_couverts` links its measurements to plants (`*`: the whole
    zone); a soil probe covers its own emplacement."""

    id: str  # sht41-z1
    modele: str  # SHT41, capacitif-sol, EZO-pH… (BOM of docs/06 §1.2)
    noeud: str
    zone: str
    mesures: list[SensorType] = Field(min_length=1)
    emplacement: str | None = None  # soil probe: field `emplacement` of its readings
    cuve: bool = False  # measures the tank of the zone (pH, EC, temp_eau, niveau_cuve)
    emplacements_couverts: list[str] | Literal["*"] = "*"
    etalonnage: dict | None = None  # {date, methode, coefficients}
    plage: tuple[float, float] | None = None  # physical range (min, max)

    def canaux(self) -> list[tuple[str, SensorType]]:
        return [(capteur_id(self.noeud, m, self.emplacement), m) for m in self.mesures]

    def couverts(self, zone: "ZoneCfg") -> list[str]:
        if self.emplacement is not None:
            return [self.emplacement]
        if self.emplacements_couverts == "*":
            return [e.id for e in zone.emplacements]
        return list(self.emplacements_couverts)


class CameraCfg(_Cfg):
    """`regions`: normalised [x, y, w, h] of each visible emplacement in the image; a
    detection is assigned to the region containing the centre of its bbox (docs/09 §4)."""

    id: str = Field(pattern=r"^[a-z0-9_-]+$")  # <camera_id> segment of the vision topic
    zone: str
    emplacements_visibles: list[str] = Field(min_length=1)
    regions: dict[str, tuple[float, float, float, float]] = Field(default_factory=dict)


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


class ReglesCfg(_Cfg):
    """Thresholds of the "classification → action" rules (docs/10 §5), `regles.yaml`."""

    confirmations: int = Field(default=3, ge=1)
    classe_conf_min: float = Field(default=0.6, ge=0, le=1)
    anomalie_seuil: float = Field(default=0.7, ge=0, le=1)
    recapture_s: float = 3600.0
    expiration_s: float = 7200.0
    hr_abaissement: float = 10.0
    hr_abaissement_h: float = 72.0
    surface_baisse: float = Field(default=0.15, gt=0, lt=1)
    surface_fenetre_h: float = 48.0
    brumisation_s: float = 30.0
    validation: dict[str, bool] = Field(default_factory=dict)  # rule id -> born `proposee`

    def needs_validation(self, rule_id: str, default: bool) -> bool:
        return self.validation.get(rule_id, default)


class SerreCfg(_Cfg):
    config_version: int = Field(ge=0)
    nom: str = "serre"
    fuseau: str = "Europe/Paris"
    tarif_kwh: float | None = None  # €/kWh, cost of the estimated consumption (docs/09 §5)
    recettes: Path | dict[str, Recipe] = Path("edge/controller/recettes.yaml")  # or inline
    regles: Path | ReglesCfg = Path("edge/controller/regles.yaml")  # or inline
    zones: list[ZoneCfg] = Field(min_length=1)
    cuves: list[CuveCfg] = Field(default_factory=list)
    actionneurs: list[ActionneurCfg] = Field(default_factory=list)
    capteurs: list[CapteurCfg] = Field(default_factory=list)
    cameras: list[CameraCfg] = Field(default_factory=list)
    hysteresis: HysteresisCfg = Field(default_factory=HysteresisCfg)
    securite: SecuriteCfg = Field(default_factory=SecuriteCfg)
    risque: RisqueCfg = Field(default_factory=RisqueCfg)
    lumiere: LumiereCfg = Field(default_factory=LumiereCfg)
    prevision: PrevisionCfg = Field(default_factory=PrevisionCfg)

    @model_validator(mode="after")
    def _check(self) -> "SerreCfg":
        zones = {z.id: z for z in self.zones}
        if len(zones) != len(self.zones):
            raise ValueError("zones en double")
        emps = {e.id: z.id for z in self.zones for e in z.emplacements}
        if len(emps) != sum(len(z.emplacements) for z in self.zones):
            raise ValueError("emplacements en double")
        seen = set()
        for a in self.actionneurs:
            if a.zone not in zones:
                raise ValueError(f"{a.id}: zone inconnue {a.zone}")
            if (a.zone, a.type) in seen:
                raise ValueError(f"{a.id}: un seul {a.type} par zone (topic cmd/{a.type})")
            seen.add((a.zone, a.type))
        declared = {c.id for c in self.cuves}
        for z in self.zones:
            if isinstance(z.cuve, str) and z.cuve not in declared:
                raise ValueError(f"{z.id}: cuve inconnue {z.cuve}")

        def in_zone(owner: str, zone: str, emplacements) -> None:
            for e in emplacements:
                if emps.get(e) != zone:
                    raise ValueError(f"{owner}: emplacement {e} hors de la zone {zone}")

        ids = set()
        for c in self.capteurs:
            if c.zone not in zones:
                raise ValueError(f"{c.id}: zone inconnue {c.zone}")
            if c.id in ids:
                raise ValueError(f"capteur {c.id} en double")
            ids.add(c.id)
            if c.cuve and zones[c.zone].cuve_id is None:
                raise ValueError(f"{c.id}: la zone {c.zone} n'a pas de cuve")
            in_zone(c.id, c.zone, c.couverts(zones[c.zone]))
        channels = [ch for c in self.capteurs for ch, _ in c.canaux()]
        if len(set(channels)) != len(channels):
            raise ValueError("deux capteurs déclarent le même canal (noeud, mesure, emplacement)")
        for cam in self.cameras:
            if cam.zone not in zones:
                raise ValueError(f"{cam.id}: zone inconnue {cam.zone}")
            in_zone(cam.id, cam.zone, cam.emplacements_visibles)
            extra = set(cam.regions) - set(cam.emplacements_visibles)
            if extra:
                raise ValueError(f"{cam.id}: régions d'emplacements non visibles {sorted(extra)}")
            for e, (x, y, w, h) in cam.regions.items():
                if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1):
                    raise ValueError(f"{cam.id}: région {e} hors de [0, 1]")
        if len({c.id for c in self.cameras}) != len(self.cameras):
            raise ValueError("caméras en double")
        return self

    def zone(self, zone: str) -> ZoneCfg:
        return next(z for z in self.zones if z.id == zone)

    def actuator(self, zone: str, actuator: Actuator | str) -> ActionneurCfg | None:
        return next((a for a in self.actionneurs if a.zone == zone and a.type == actuator), None)

    def camera(self, camera: str) -> CameraCfg | None:
        return next((c for c in self.cameras if c.id == camera), None)

    def plant_at(self, emplacement: str) -> PlanteCfg | None:
        for z in self.zones:
            for e in z.emplacements:
                if e.id == emplacement:
                    return e.plante
        return None

    def emplacement_of(
        self, camera: str, bbox: tuple[float, float, float, float] | None
    ) -> str | None:
        """Emplacement of a detection of `camera` (docs/09 §4), see `resolve_emplacement`."""
        cam = self.camera(camera)
        if cam is None:
            return None
        return resolve_emplacement(
            bbox, [(e, cam.regions.get(e)) for e in cam.emplacements_visibles]
        )

    def resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else ROOT / path

    def load_regles(self) -> ReglesCfg:
        if isinstance(self.regles, ReglesCfg):
            return self.regles
        path = self.resolve(self.regles)
        if not path.exists():
            log.warning("%s absent : seuils par défaut des règles vision", path)
            return ReglesCfg()
        return ReglesCfg.model_validate(yaml.safe_load(path.read_text()) or {})

    def load_recipes(self) -> dict[str, Recipe]:
        if isinstance(self.recettes, dict):
            return dict(self.recettes)
        return load_recipes(self.resolve(self.recettes))


class Greenhouse:
    """Loaded configuration + recipes, with the setpoints of each zone."""

    def __init__(self, cfg: SerreCfg, recipes: dict[str, Recipe], especes: set[str] | None = None):
        from .coherence import check, known_species

        self.cfg, self.recipes = cfg, recipes
        self.regles = cfg.load_regles()
        self.especes = known_species() if especes is None else especes
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
        self.warnings = check(cfg, self.especes)  # configuration warnings (docs/09 §3)
        for w in self.warnings:
            log.warning("configuration : %s", w)

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

    def vision_auto(self, camera: str) -> bool:
        """May the vision results of this camera trigger automatic decisions? Not when it
        only sees plants of species outside the taxonomy (docs/09 §2): their
        classifications are shown, only `score_anomalie` gives a simple alert. An
        undeclared camera, or one that sees no plant, keeps the default behaviour."""
        cam = self.cfg.camera(camera)
        if cam is None:
            return True
        plants = [p for e in cam.emplacements_visibles if (p := self.cfg.plant_at(e))]
        return not plants or any(p.espece in self.especes for p in plants)


def resolve_emplacement(
    bbox: tuple[float, float, float, float] | None,
    regions: list[tuple[str, tuple[float, float, float, float] | list[float] | None]],
) -> str | None:
    """Emplacement of a detection (docs/09 §4): the region containing the bbox centre;
    otherwise (phase 1 whole image, or no matching region), the only emplacement seen by
    the camera if any. `regions`: (visible emplacement, its region or None)."""
    if bbox is not None:
        cx, cy = bbox[0] + bbox[2] / 2, bbox[1] + bbox[3] / 2
        for emplacement, region in regions:
            if region is None:
                continue
            x, y, w, h = region
            if x <= cx <= x + w and y <= cy <= y + h:
                return emplacement
    return regions[0][0] if len(regions) == 1 else None


def load_greenhouse(path: Path = DEFAULT_CONFIG) -> Greenhouse:
    cfg = SerreCfg.model_validate(yaml.safe_load(Path(path).read_text()))
    return Greenhouse(cfg, cfg.load_recipes())


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
