"""Disease risk index (docs/06 §4): leaf wetness, mean temperature, recent vision.

`risque = f(heures d'humectation estimées, T° moyenne, détections vision récentes)`, here
with known agronomic rules first (mildew: HR > 90 % for more than 10 h at 10–25 °C); the
weights are to be learnt on our data later.

Rule `maladie.mildiou.ventilation` (docs/10 §5): mildew conditions, or mildew confirmed
by vision (N consecutive captures) in a humid atmosphere → preventive ventilation of
15 min, at most once per `periode_s`, and a warning.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from common.mqtt import Actuator, Preuves, PreuveVision, SensorType, VisionResult

from .context import Ctx
from .decisions import AlertSpec, Order, Proposal, evidence, fmt, rule
from .state import ZoneState
from .vision_alerts import abnormal_score, dominant_class

RULE_ID = "maladie.mildiou.ventilation"
VISION_SEUIL = 0.6
CONFIRMATIONS = 3


@dataclass
class RiskIndex:
    score: float  # 0..1
    humectation_h: float
    t_moyenne: float | None
    vision: list[VisionResult]  # confirming captures (latest first), empty if none
    conditions: bool  # agronomic conditions met


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


def mildew_risk(ctx: Ctx) -> RiskIndex:
    cfg = ctx.gh.cfg.risque
    wet = ctx.zs.spell(cfg.hr_humectation).hours(ctx.now)
    t12 = ctx.zs.mean(SensorType.TEMPERATURE, ctx.now, timedelta(hours=12))
    vision = confirmed(ctx.zs, "mildiou", allowed=ctx.gh.vision_auto)
    t_ok = t12 is not None and cfg.t_min <= t12 <= cfg.t_max
    hr = ctx.value(SensorType.HUMIDITE)
    conditions = t_ok and (wet >= cfg.humectation_h or (bool(vision) and (hr or 0) > 85))
    score = min(1.0, wet / cfg.humectation_h) * (1.0 if t_ok else 0.3)
    if vision:
        score = min(1.0, score + 0.5)
    return RiskIndex(round(score, 3), wet, t12, vision, conditions)


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


def mildew(ctx: Ctx) -> list[Proposal]:
    cfg = ctx.gh.cfg.risque
    risk = mildew_risk(ctx)
    if not risk.conditions:
        return []
    zone = ctx.zone
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
    why = (
        f"HR > {cfg.hr_humectation:g} % depuis {fmt(risk.humectation_h)} h "
        f"à {fmt(risk.t_moyenne)} °C"
    )
    if risk.vision:
        why += f", mildiou vu sur {risk.vision[0].camera} ({CONFIRMATIONS} captures)"
    orders, fired = [], ctx.zs.rule_fired.get(RULE_ID)
    if ctx.act(Actuator.VENTILO) and (
        fired is None or ctx.now - fired >= timedelta(seconds=cfg.periode_s)
    ):
        orders.append(
            Order(Actuator.VENTILO, "on", None, cfg.ventilation_s, "ventilation préventive mildiou")
        )
        if ctx.act(Actuator.VENTILO).commande == "pwm":
            orders[0] = Order(Actuator.VENTILO, "pwm", 100.0, cfg.ventilation_s, orders[0].texte)
    msg = f"{why} → risque mildiou {fmt(risk.score, 2)}"
    if orders:
        msg += f", ventilation {cfg.ventilation_s / 60:g} min"
    return [
        Proposal(
            zone=zone,
            regle=rule(RULE_ID),
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
                capteurs=capteurs,
                vision=[_vision_evidence(r) for r in risk.vision],
                consignes=ctx.sp.as_evidence() if ctx.sp else {},
            ),
        )
    ]
