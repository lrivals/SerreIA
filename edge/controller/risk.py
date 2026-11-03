"""Disease risk indices (docs/06 §4, docs/22 L5, L7): mildew and Botrytis.

Parameters per pathogen and crop: `pathogenes.yaml` (`pathogenes.py`), each with its sources.

Mildew (docs/22 L5), per species of the zone:
- leaf wetness duration (LWD) = hours with HR above `risque.hr_humectation`, and the mean
  temperature **during** the wetness (TLWD), not over a fixed 12 h;
- infection when LWD ≥ `lwd_min_h`, TLWD inside `t_humectation` and, when the block asks
  for it, LWD × TLWD ≥ `degres_heures_min` (two-stage model, `2022-liu#004.0`);
- then incubation, when the block gives a rate table: progress += rate(T) × dt at each tick,
  symptoms expected at progress 1 (67 h at 20 °C for cucumber downy mildew). Species
  without a sourced block (tomato…) keep the historical 10 h at 10–25 °C and no incubation;
- mildew confirmed by vision (N captures) in humid air also gives the conditions.
The infection states live in `ZoneState.infections` (lost when the controller restarts).

Rule `maladie.mildiou.ventilation` (docs/10 §5): conditions → preventive ventilation of
15 min, at most once per `periode_s`, and a warning; an incubation still running once the
air is dry → info alert with the expected date of symptoms.

Rule `maladie.botrytis.chauffage_ventilation` (docs/22 L7): at night, mean T° over 1 h in
15–22 °C with HR > 90 % and VPD < 0.5 kPa (`2026-fanourakis#027.0`) → warning; in the last
hours before the day (condensation after the night cooling, `#013.2`), heating and
ventilation together, at most once per `periode_s`.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from common.mqtt import Actuator, Preuves, PreuveVision, SensorType, VisionResult

from .context import Ctx
from .decisions import AlertSpec, Order, Proposal, evidence, fmt, rule
from .pathogenes import MildewParams
from .psychro import point_de_rosee, vpd
from .state import Infection, ZoneState
from .vision_alerts import abnormal_score, dominant_class

RULE_ID = "maladie.mildiou.ventilation"
BOTRYTIS_ID = "maladie.botrytis.chauffage_ventilation"
VISION_SEUIL = 0.6
CONFIRMATIONS = 3
INCUBATION_GARDE = timedelta(hours=24)  # an infection record is kept this long after symptoms


@dataclass
class SpeciesRisk:
    espece: str  # species of the zone (the infection key)
    params: MildewParams
    infected: bool  # infection criterion met now
    etat: str  # sain | infection | incubation | symptomes_attendus
    progression: float = 0.0
    symptomes: datetime | None = None  # expected date of symptoms


@dataclass
class RiskIndex:
    score: float  # 0..1
    humectation_h: float
    t_moyenne: float | None  # 12 h mean (evidence)
    vision: list[VisionResult]  # confirming captures (latest first), empty if none
    conditions: bool  # agronomic conditions met
    t_humectation: float | None = None  # mean T° during the current wet spell
    especes: list[SpeciesRisk] = field(default_factory=list)

    @property
    def degres_heures(self) -> float | None:
        if self.t_humectation is None:
            return None
        return self.humectation_h * self.t_humectation


def confirmed(
    zs: ZoneState,
    maladie: str,
    n: int = CONFIRMATIONS,
    seuil: float = VISION_SEUIL,
    allowed: Callable[[str], bool] = lambda camera: True,
) -> list[VisionResult]:
    """Last n captures of one camera all abnormal with the same disease class. Cameras
    not `allowed` (they only see species outside the taxonomy, docs/09 §2) are ignored."""
    by_cam: dict[str, list[VisionResult]] = {}
    for r in zs.vision:
        if not allowed(r.camera):
            continue
        by_cam.setdefault(r.camera, []).append(r)
    for results in by_cam.values():
        last = sorted(results, key=lambda r: r.ts)[-n:]
        if len(last) == n and all(
            abnormal_score(r) > seuil and (dominant_class(r) or "").endswith(f"/{maladie}")
            for r in last
        ):
            return last[::-1]
    return []


def zone_species(ctx: Ctx) -> list[str]:
    """Species of the plants of the zone (sorted, unique); "defaut" for an empty zone."""
    return sorted({p.espece for p in ctx.zcfg.plants}) or ["defaut"]


def wetness(ctx: Ctx) -> tuple[float, float | None]:
    """Current wet spell: (hours, mean T° during it)."""
    wet = ctx.zs.spell(ctx.gh.cfg.risque.hr_humectation).hours(ctx.now)
    if wet <= 0:
        return 0.0, None
    return wet, ctx.zs.mean(SensorType.TEMPERATURE, ctx.now, timedelta(hours=wet))


def _expected(ctx: Ctx, params: MildewParams, rec: Infection) -> datetime | None:
    """Expected date of symptoms at the current temperature."""
    if params.incubation is None:
        return None
    t = ctx.value(SensorType.TEMPERATURE)
    rate = params.incubation.rate(t if t is not None else 20.0)
    if rate <= 0:
        return None
    left = max(0.0, 1 - rec.progression)
    return (rec.maj or ctx.now) + timedelta(hours=left / rate)


def mildew_risk(ctx: Ctx) -> RiskIndex:
    cfg = ctx.gh.cfg.risque
    wet, t_wet = wetness(ctx)
    t12 = ctx.zs.mean(SensorType.TEMPERATURE, ctx.now, timedelta(hours=12))
    vision = confirmed(ctx.zs, "mildiou", allowed=ctx.gh.vision_auto)
    hr = ctx.value(SensorType.HUMIDITE)
    especes = []
    for espece in zone_species(ctx):
        params = ctx.gh.pathogenes.mildew(espece, cfg)
        infected = params.infected(wet, t_wet)
        sr = SpeciesRisk(espece, params, infected, "infection" if infected else "sain")
        rec = ctx.zs.infections.get(f"mildiou/{espece}")
        if rec is not None:
            sr.progression = rec.progression
            if params.incubation is not None:
                sr.etat = "symptomes_attendus" if rec.progression >= 1 else "incubation"
            else:
                sr.etat = "infection"
            sr.symptomes = _expected(ctx, params, rec)
        especes.append(sr)
    default = ctx.gh.pathogenes.mildew("defaut", cfg)
    t_ok = t12 is not None and default.t_humectation[0] <= t12 <= default.t_humectation[1]
    by_vision = bool(vision) and (hr or 0) > cfg.hr_vision and t_ok
    conditions = any(s.infected for s in especes) or by_vision
    lwd_min = min(s.params.lwd_min_h for s in especes)
    t_fit = any(
        t_wet is not None and s.params.t_humectation[0] <= t_wet <= s.params.t_humectation[1]
        for s in especes
    )
    score = min(1.0, wet / lwd_min) * (1.0 if t_fit or (wet == 0 and t_ok) else 0.3)
    if vision:
        score = min(1.0, score + 0.5)
    return RiskIndex(round(score, 3), wet, t12, vision, conditions, t_wet, especes)


def update_infections(ctx: Ctx, risk: RiskIndex) -> None:
    """Advance the infection state machine of each species of the zone by one tick."""
    t = ctx.value(SensorType.TEMPERATURE)
    for sr in risk.especes:
        key = f"mildiou/{sr.espece}"
        rec = ctx.zs.infections.get(key)
        inc = sr.params.incubation
        if rec is None:
            if sr.infected:
                ctx.zs.infections[key] = Infection(debut=ctx.now, maj=ctx.now)
            continue
        if inc is None:  # no sourced incubation: the state follows the conditions
            if not sr.infected:
                del ctx.zs.infections[key]
            continue
        if t is not None and rec.maj is not None:
            dt_h = max(0.0, (ctx.now - rec.maj).total_seconds() / 3600)
            was = rec.progression
            rec.progression += inc.rate(t) * dt_h
            if was < 1 <= rec.progression:
                rec.atteinte = ctx.now  # reached: start of the keeping delay
        rec.maj = ctx.now
        if rec.progression >= 1 and rec.atteinte is not None:
            if ctx.now - rec.atteinte > INCUBATION_GARDE and not sr.infected:
                del ctx.zs.infections[key]


def _vision_evidence(r: VisionResult) -> PreuveVision:
    d = max((d for d in r.detections if d.sante == "anormal"), key=lambda d: d.sante_conf)
    return PreuveVision(
        camera=r.camera,
        image_id=r.image_id,
        modele=r.modele,
        classe=d.classe,
        classe_conf=d.classe_conf,
        sante=d.sante,
        sante_conf=d.sante_conf,
        espece=d.espece,
        espece_conf=d.espece_conf,
        bbox=d.bbox,
        score_anomalie=r.score_anomalie,
        confirmations=CONFIRMATIONS,
    )


def _full(ctx: Ctx, actuator: Actuator, duree: float, texte: str) -> Order:
    if ctx.act(actuator).commande == "pwm":
        return Order(actuator, "pwm", 100.0, duree, texte)
    return Order(actuator, "on", None, duree, texte)


def _state_text(risk: RiskIndex, tz) -> str:
    parts = []
    for s in risk.especes:
        if s.etat == "sain":
            continue
        txt = f"{s.espece} : {s.etat}"
        if s.params.espece == "defaut":
            txt += " (seuils non sourcés)"
        if s.params.incubation is not None:
            txt += f" {fmt(min(s.progression, 1) * 100, 0)} %"
            if s.symptomes is not None and s.progression < 1:
                txt += f", symptômes attendus vers {s.symptomes.astimezone(tz):%d/%m %H:%M}"
        parts.append(txt)
    return " ; ".join(parts)


def mildew(ctx: Ctx) -> list[Proposal]:
    cfg = ctx.gh.cfg.risque
    risk = mildew_risk(ctx)
    update_infections(ctx, risk)
    risk = mildew_risk(ctx)  # with the updated states
    zone = ctx.zone
    if not risk.conditions:
        return _incubation_watch(ctx, risk)
    capteurs = [
        evidence(
            zone,
            SensorType.HUMIDITE,
            valeur=risk.humectation_h,
            unite="h",
            agregat="duree_au_dessus",
            seuil=cfg.hr_humectation,
        ),
        evidence(
            zone, SensorType.TEMPERATURE, valeur=risk.t_moyenne, unite="°C", agregat="moyenne_12h"
        ),
        evidence(zone, SensorType.HUMIDITE, valeur=risk.score, unite="", agregat="indice_risque"),
    ]
    if risk.t_humectation is not None:
        capteurs += [
            evidence(zone, SensorType.TEMPERATURE, valeur=risk.t_humectation, unite="°C",
                     agregat="moyenne_humectation"),
            evidence(zone, SensorType.TEMPERATURE, valeur=risk.degres_heures, unite="h·°C",
                     agregat="degres_heures"),
        ]  # fmt: skip
    t_txt = risk.t_humectation if risk.t_humectation is not None else risk.t_moyenne
    why = f"HR > {cfg.hr_humectation:g} % depuis {fmt(risk.humectation_h)} h à {fmt(t_txt)} °C"
    if risk.vision:
        why += f", mildiou vu sur {risk.vision[0].camera} ({CONFIRMATIONS} captures)"
    orders, fired = [], ctx.zs.rule_fired.get(RULE_ID)
    if ctx.act(Actuator.VENTILO) and (
        fired is None or ctx.now - fired >= timedelta(seconds=cfg.periode_s)
    ):
        orders.append(
            _full(ctx, Actuator.VENTILO, cfg.ventilation_s, "ventilation préventive mildiou")
        )
    msg = f"{why} → risque mildiou {fmt(risk.score, 2)}"
    state = _state_text(risk, ctx.local.tzinfo)
    if state:
        msg += f" ({state})"
    if orders:
        msg += f", ventilation {cfg.ventilation_s / 60:g} min"
    return [
        Proposal(
            zone=zone,
            regle=rule(RULE_ID, 2),
            niveau=1,
            type="exceptionnelle",
            explication=msg,
            orders=orders,
            alerte=AlertSpec(
                "warning",
                f"{zone} : risque mildiou ({why})",
                f"{zone}/{RULE_ID}",
                f"{zone} : conditions mildiou terminées",
            ),
            preuves=Preuves(
                capteurs=capteurs + _incubation_evidence(ctx, risk),
                vision=[_vision_evidence(r) for r in risk.vision],
                consignes=ctx.sp.as_evidence() if ctx.sp else {},
            ),
        )
    ]


def _incubation_evidence(ctx: Ctx, risk: RiskIndex):
    return [
        evidence(ctx.zone, SensorType.TEMPERATURE, valeur=min(s.progression, 1.0), unite="",
                 agregat="incubation")
        for s in risk.especes
        if s.params.incubation is not None and s.etat != "sain"
    ]  # fmt: skip


def _incubation_watch(ctx: Ctx, risk: RiskIndex) -> list[Proposal]:
    """Dry air but an incubation running: info alert with the expected symptoms."""
    running = [s for s in risk.especes if s.etat in ("incubation", "symptomes_attendus")]
    if not running:
        return []
    msg = f"mildiou en incubation ({_state_text(risk, ctx.local.tzinfo)}) : inspecter les plantes"
    return [
        Proposal(
            zone=ctx.zone,
            regle=rule(RULE_ID, 2),
            niveau=1,
            type="exceptionnelle",
            explication=msg,
            alerte=AlertSpec(
                "info",
                f"{ctx.zone} : {msg}",
                f"{ctx.zone}/maladie.mildiou.incubation",
                f"{ctx.zone} : incubation mildiou terminée",
            ),
            preuves=Preuves(
                capteurs=_incubation_evidence(ctx, risk),
                consignes=ctx.sp.as_evidence() if ctx.sp else {},
            ),
        )
    ]


# --- Botrytis (docs/22 L7) ----------------------------------------------------------------


@dataclass
class BotrytisIndex:
    conditions: bool
    t: float | None
    hr: float | None
    vpd: float | None
    ecart_rosee: float | None
    fin_de_nuit: bool


def botrytis_risk(ctx: Ctx) -> BotrytisIndex:
    cfg = ctx.gh.pathogenes.botrytis
    hour = timedelta(hours=1)
    t = ctx.zs.mean(SensorType.TEMPERATURE, ctx.now, hour)
    hr = ctx.zs.mean(SensorType.HUMIDITE, ctx.now, hour)
    if t is None or hr is None or ctx.sp is None:
        return BotrytisIndex(False, t, hr, None, None, False)
    v, gap = vpd(t, hr), t - point_de_rosee(t, hr)
    start, _ = ctx.window()
    nxt = start if start > ctx.local else start + timedelta(days=1)
    end_of_night = not ctx.jour and nxt - ctx.local <= timedelta(hours=cfg.fenetre_fin_nuit_h)
    ok = not ctx.jour and cfg.t[0] <= t <= cfg.t[1] and hr > cfg.hr_min and v < cfg.vpd_max
    return BotrytisIndex(ok, t, hr, v, gap, end_of_night)


def botrytis(ctx: Ctx) -> list[Proposal]:
    b = botrytis_risk(ctx)
    if not b.conditions:
        return []
    cfg, risque = ctx.gh.pathogenes.botrytis, ctx.gh.cfg.risque
    zone = ctx.zone
    why = (
        f"nuit à {fmt(b.t)} °C, HR {fmt(b.hr)} %, VPD {fmt(b.vpd, 2)} kPa "
        f"(rosée à {fmt(b.ecart_rosee)} °C de l'air)"
    )
    orders, fired = [], ctx.zs.rule_fired.get(BOTRYTIS_ID)
    due = fired is None or ctx.now - fired >= timedelta(seconds=risque.periode_s)
    if b.fin_de_nuit and due and ctx.act(Actuator.CHAUFFAGE) and ctx.act(Actuator.VENTILO):
        orders = [
            _full(ctx, Actuator.CHAUFFAGE, cfg.chauffage_s, "Botrytis : chauffer pour sécher"),
            _full(ctx, Actuator.VENTILO, cfg.ventilation_s, "Botrytis : évacuer l'humidité"),
        ]
    msg = f"{why} → risque Botrytis"
    if orders:
        msg += (
            f", fin de nuit : chauffage {cfg.chauffage_s / 60:g} min et ventilation "
            f"{cfg.ventilation_s / 60:g} min"
        )
    capteurs = [
        evidence(zone, SensorType.TEMPERATURE, valeur=b.t, unite="°C", agregat="moyenne_1h"),
        evidence(zone, SensorType.HUMIDITE, valeur=b.hr, unite="%", agregat="moyenne_1h",
                 seuil=cfg.hr_min),
        evidence(zone, SensorType.HUMIDITE, valeur=b.vpd, unite="kPa", agregat="vpd",
                 seuil=cfg.vpd_max),
        evidence(zone, SensorType.TEMPERATURE, valeur=b.ecart_rosee, unite="°C",
                 agregat="ecart_point_de_rosee"),
    ]  # fmt: skip
    return [
        Proposal(
            zone=zone,
            regle=rule(BOTRYTIS_ID),
            niveau=1,
            type="exceptionnelle",
            explication=msg,
            orders=orders,
            alerte=AlertSpec(
                "warning",
                f"{zone} : risque Botrytis ({why})",
                f"{zone}/{BOTRYTIS_ID}",
                f"{zone} : conditions Botrytis terminées",
            ),
            preuves=Preuves(capteurs=capteurs, consignes=ctx.sp.as_evidence()),
        )
    ]


def diseases(ctx: Ctx) -> list[Proposal]:
    """All the disease risk rules of a zone, in evaluation order."""
    return mildew(ctx) + botrytis(ctx)
