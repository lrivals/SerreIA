"""Scripted scenarios of the simulator (docs/16 §2): `python -m sim --scenario <nom>`.

`sim/scenarios/<nom>.yaml` describes the scenario:

    nom: journee
    debut: 2026-07-14T20:00+02:00
    duree_h: 28
    seed: 1
    meteo: {nuages: [{de: J1 09:00, a: J1 12:00, couverture: 1.0}]}   # forced cloud cover
    pannes:                                    # syntax of sim/faults.py (minutes), or:
      - fige:z1/temperature@840-930
      - {panne: "deconnexion:esp32-02", de: J1 13:00, a: J1 13:40}
    forcages:                                  # on the true state of a zone
      - {grandeur: humidite, zone: z1, valeur: 93, de: 0h, a: J1 06:00}         # held
      - {grandeur: humidite_sol, zone: z1, emplacement: z1-A1, valeur: 30, de: J1 15:00}  # once
      - {grandeur: ph, zone: z2, derive: +0.4, de: J1 13:00, a: J1 14:00}       # drift
    vision:                                    # fake VisionResult
      - {t: J2 00:00, camera: cam-z1-a, emplacement: z1-A1, classe: tomate/maladie/mildiou,
         conf: 0.81}
    cameras: false     # the simulated cameras stay off (default: camera_service not running)

Times are "J<n> HH:MM" (local clock of `debut`, J0 = its day), or offsets from `debut`:
"9h", "13h40", "26h", "90min", a number of minutes (as the faults). Forcings act on the
zone model, not on the readings, so the controller still regulates against them: a held
`valeur` overrides the state, a `derive` is added to its dynamics (on a quantity that
relaxes, T° or HR, the net effect is smaller than the drift). `run_fast` replays a
scenario at full speed on an in-memory bus with the controller, optionally ingested into
a database.
"""

import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

import yaml

from common.mqtt import Detection, VisionResult, vision_topic

from .faults import Faults, parse_fault

SCENARIOS = Path(__file__).with_name("scenarios")
_CLOCK = re.compile(r"^J(\d+)\s+(\d{1,2}):(\d{2})$")
_OFFSET = re.compile(r"^(\d+(?:\.\d+)?)h(\d{1,2})?$|^(\d+(?:\.\d+)?)\s*min$")
# quantity -> attribute of sim.model.ZoneModel
ATTRIBUTES = {
    "temperature": "t",
    "humidite": "hr",
    "co2": "co2",
    "ph": "ph",
    "ec": "ec",
    "niveau_cuve": "niveau",
    "presence": "presence",
    "humidite_sol": "soil",
}


def parse_offset(value) -> timedelta:
    """ "9h", "13h40", "26h", "90min" or minutes (int/float) → timedelta."""
    if isinstance(value, int | float):
        return timedelta(minutes=value)
    m = _OFFSET.match(str(value).strip())
    if not m:
        raise ValueError(f"durée invalide {value!r} (ex. 9h, 13h40, 90min)")
    if m.group(3) is not None:
        return timedelta(minutes=float(m.group(3)))
    return timedelta(hours=float(m.group(1)), minutes=int(m.group(2) or 0))


def parse_time(value, debut: datetime) -> datetime:
    """ "J1 10:00" (local clock of `debut`, J0 = its day) or an offset from `debut`."""
    m = _CLOCK.match(str(value).strip())
    if m:
        day, hh, mm = (int(x) for x in m.groups())
        t = datetime.combine(debut.date() + timedelta(days=day), time(hh, mm), debut.tzinfo)
        if t < debut:
            raise ValueError(f"{value!r} avant le début du scénario")
        return t
    return debut + parse_offset(value)


def _datetime(value) -> datetime:
    t = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return t if t.tzinfo is not None else t.replace(tzinfo=UTC)


@dataclass
class Forcage:
    grandeur: str
    zone: str
    de: datetime
    a: datetime | None = None
    valeur: float | None = None
    derive: float | None = None
    emplacement: str | None = None
    done: bool = False  # a one-shot `valeur` (no `a`) was applied

    def __post_init__(self):
        if self.grandeur not in ATTRIBUTES:
            raise ValueError(f"grandeur {self.grandeur!r} non forçable ({', '.join(ATTRIBUTES)})")
        if (self.valeur is None) == (self.derive is None):
            raise ValueError(f"forçage {self.grandeur} : `valeur` ou `derive`, pas les deux")
        if self.derive is not None and self.a is None:
            raise ValueError(f"forçage {self.grandeur} : une dérive a besoin de `a`")
        if self.grandeur == "humidite_sol" and not self.emplacement:
            raise ValueError("forçage humidite_sol : `emplacement` obligatoire")


@dataclass
class VisionEvent:
    t: datetime
    camera: str
    emplacement: str
    classe: str
    conf: float = 0.85


@dataclass
class Scenario:
    nom: str
    debut: datetime
    duree_h: float
    seed: int = 0
    nuages: list[tuple[datetime, datetime, float]] = field(default_factory=list)
    pannes: list[str] = field(default_factory=list)
    forcages: list[Forcage] = field(default_factory=list)
    vision: list[VisionEvent] = field(default_factory=list)
    cameras: bool = False
    path: Path | None = None

    @classmethod
    def load(cls, name_or_path: str | Path) -> "Scenario":
        path = Path(name_or_path)
        if not path.suffix:
            path = SCENARIOS / f"{name_or_path}.yaml"
        return cls.parse(yaml.safe_load(path.read_text()), path)

    @classmethod
    def parse(cls, raw: dict, path: Path | None = None) -> "Scenario":
        debut = _datetime(raw["debut"])
        at = lambda v: parse_time(v, debut)  # noqa: E731
        meteo = raw.get("meteo") or {}
        nuages = [
            (at(n["de"]), at(n["a"]), float(n["couverture"])) for n in meteo.get("nuages", [])
        ]
        forcages = []
        for f in raw.get("forcages") or []:
            f = dict(f)
            f["de"] = at(f["de"])
            f["a"] = at(f["a"]) if f.get("a") is not None else None
            forcages.append(Forcage(**f))
        vision = []
        for v in raw.get("vision") or []:
            v = dict(v)
            v["t"] = at(v["t"])
            vision.append(VisionEvent(**v))
        sc = cls(
            nom=raw["nom"],
            debut=debut,
            duree_h=float(raw["duree_h"]),
            seed=int(raw.get("seed", 0)),
            nuages=nuages,
            pannes=[_fault_spec(p, debut) for p in raw.get("pannes") or []],
            forcages=forcages,
            vision=sorted(vision, key=lambda v: v.t),
            cameras=bool(raw.get("cameras", False)),
            path=path,
        )
        sc.faults()  # validates the fault syntax early
        return sc

    @property
    def fin(self) -> datetime:
        return self.debut + timedelta(hours=self.duree_h)

    @property
    def attendus_path(self) -> Path | None:
        if self.path is None:
            return None
        p = self.path.with_name(f"{self.path.stem}.attendus.yaml")
        return p if p.is_file() else None

    def faults(self, extra: list[str] = ()) -> Faults:
        return Faults([parse_fault(s, self.debut) for s in [*self.pannes, *extra]])

    def injector(self, layout) -> "Injector":
        return Injector(self, layout)


def _fault_spec(p, debut: datetime) -> str:
    """A fault of sim/faults.py: its CLI string, or {panne, de, a} with scenario times."""
    if isinstance(p, str):
        return p
    minutes = lambda v: f"{(parse_time(v, debut) - debut).total_seconds() / 60:g}"  # noqa: E731
    end = f"-{minutes(p['a'])}" if p.get("a") is not None else ""
    return f"{p['panne']}@{minutes(p['de'])}{end}"


class Injector:
    """What `Simulation.step` asks the scenario: weather, forcings, fake vision."""

    def __init__(self, scenario: Scenario, layout):
        self.sc = scenario
        self.forcages = [replace(f, done=False) for f in scenario.forcages]
        self.pending = list(scenario.vision)
        self.cameras = {c.id: c for c in layout.cameras}
        if not scenario.cameras:
            layout.cameras = []

    @staticmethod
    def _in(t: datetime, de: datetime, a: datetime | None) -> bool:
        return de <= t and (a is None or t < a)

    def weather(self, t: datetime, w):
        for de, a, c in self.sc.nuages:
            if self._in(t, de, a):
                clear = w.rayonnement / (1 - 0.75 * w.nuages)
                return replace(w, nuages=c, rayonnement=clear * (1 - 0.75 * c))
        return w

    def force(self, zone: str, model, t: datetime, dt: float) -> None:
        for f in self.forcages:
            if f.zone != zone or not self._in(t, f.de, f.a) or f.done:
                continue
            attr = ATTRIBUTES[f.grandeur]
            if f.derive is not None:
                rate = f.derive / (f.a - f.de).total_seconds()
                self._set(model, f, attr, self._get(model, f, attr) + rate * dt)
            else:
                self._set(model, f, attr, f.valeur)
                if f.a is None:
                    f.done = True
            if attr == "presence":  # held: the random visits of the model stay out
                model._presence_until = t + timedelta(seconds=1.5 * dt)

    @staticmethod
    def _get(model, f: Forcage, attr: str) -> float:
        return model.soil[f.emplacement] if attr == "soil" else getattr(model, attr)

    @staticmethod
    def _set(model, f: Forcage, attr: str, value: float) -> None:
        if attr == "soil":
            model.soil[f.emplacement] = value
        elif attr == "presence":
            model.presence = int(round(value))
        else:
            setattr(model, attr, value)

    def vision(self, t: datetime) -> list[tuple[str, VisionResult]]:
        out = []
        while self.pending and self.pending[0].t <= t:
            out.append(self._result(self.pending.pop(0), t))
        return out

    def _result(self, ev: VisionEvent, t: datetime) -> tuple[str, VisionResult]:
        cam = self.cameras.get(ev.camera)
        if cam is None:
            raise ValueError(f"caméra inconnue {ev.camera!r}")
        if ev.emplacement not in cam.regions:
            raise ValueError(f"{ev.emplacement} n'est pas vu par {ev.camera}")
        region = cam.regions[ev.emplacement]
        bbox = None
        if region is not None:
            x, y, w, h = region
            bbox = (x + w / 4, y + h / 4, w / 2, h / 2)
        espece, sante, _ = ev.classe.split("/", 2)
        sain = sante == "sain"
        d = Detection(bbox=bbox, espece=espece, espece_conf=0.95,
                      sante="sain" if sain else "anormal", sante_conf=0.9, classe=ev.classe,
                      classe_conf=ev.conf)  # fmt: skip
        result = VisionResult(
            ts=t,
            camera=cam.id,
            image_id=f"{cam.id}-{t:%Y%m%dT%H%M%S}",
            modele="scenario",
            detections=[d],
            score_anomalie=0.1 if sain else 0.6,
            surface_verte_px=50_000,
        )
        return vision_topic(cam.zone, cam.id), result


@dataclass
class Run:
    scenario: Scenario
    log: list[tuple[str, bytes]]
    sim: object
    sessions: object = None
    consommation: dict | None = None


def run_fast(scenario: Scenario, sessions=None, config: Path | None = None,
             extra_faults: list[str] = ()) -> Run:  # fmt: skip
    """The scenario at full speed: simulator + controller on an in-memory bus, ingested
    into `sessions` (seeded database) when given, consumption of every day computed."""
    from edge.controller.config import DEFAULT_CONFIG
    from edge.controller.service import NODE, build
    from edge.publisher import LoopbackBus, LoopbackPublisher

    from .simulation import Simulation

    bus = LoopbackBus()
    clock = {"t": scenario.debut}
    ingestor = job = None
    if sessions is not None:
        from backend.ingestion.__main__ import ConsumptionJob
        from backend.ingestion.mqtt_ingest import Ingestor

        ingestor = Ingestor(sessions, clock=lambda: clock["t"])
        ingestor.attach(bus)
        job = ConsumptionJob(sessions)
    controller = build(config or DEFAULT_CONFIG, LoopbackPublisher(NODE, bus))
    sim = Simulation(LoopbackPublisher("sim", bus), scenario.debut, scenario.seed,
                     scenario.faults(extra_faults), controller=controller,
                     scenario=scenario)  # fmt: skip
    while sim.t < scenario.fin:
        sim.step()
        clock["t"] = sim.t
        if job is not None:
            job.maybe_run(sim.t)
    consommation = None
    if sessions is not None:
        ingestor.close()
        consommation = consumption_days(sessions, scenario.debut, sim.t)
    return Run(scenario, bus.log, sim, sessions, consommation)


def consumption_days(sessions, start: datetime, end: datetime) -> dict:
    """Daily consumption {kwh, litres, ml, cout, dli: {zone: mol/m²}} of every local day
    of the run, by date."""
    from zoneinfo import ZoneInfo

    from sqlalchemy import select

    from backend.consumption import compute_day
    from backend.db.models import LumiereJour, Serre

    out = {}
    with sessions.begin() as s:
        tz = ZoneInfo(s.scalars(select(Serre)).first().fuseau)
        day = start.astimezone(tz).date()
        last = (end - timedelta(seconds=1)).astimezone(tz).date()  # a run ending at 00:00
        while day <= last:
            totals = dict(compute_day(s, day, end))
            rows = s.scalars(select(LumiereJour).where(LumiereJour.jour == day))
            totals["dli"] = {r.zone: r.dli_total for r in rows if r.dli_total is not None}
            out[day.isoformat()] = totals
            day += timedelta(days=1)
    return out
