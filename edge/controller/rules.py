"""Level 1, rules and regulators (docs/06 §4), each with a stable and versioned id.

| Rule id | Behaviour |
|---|---|
| `climat.temperature.ventilation` | T > max of the recipe → fan on; off below max − hysteresis |
| `climat.temperature.chauffage` | T < min → heating on; off above min + hysteresis |
| `climat.humidite.ventilation` | HR > max → fan on (not when T < min); off below max − hysteresis |
| `climat.humidite.brumisation` | HR < min → misting `duree_s`, at most every `delai_min_s` |
| `ph.dosage` | pH > max → one pH− pulse, wait `melange_s`, re-measure, never continuous |
| `ec.nutriments` | EC < min → one pulse of A and of B, same logic; EC > max → alert |
| `lumiere.photoperiode` | LEDs only inside the photoperiod; with lux + DLI target: complement |
| `sol.arrosage` | soil of an emplacement < min of its recipe → watering, every `delai_min_s` |
| `hydro.circulation` | hydro zone: nutrient pump cycles of `duree_s` every `delai_min_s` |
| `presence.intrusion` | presence outside the declared ranges (night) → alert; inside: logged |

Rules are stateless and evaluated at every tick: they return what they want and the
controller only publishes what differs from the real actuator state (`etat/`). An "off"
is only proposed by the rule that switched the actuator on (`ZoneState.owner`).
"""

import logging
from datetime import timedelta

from common.mqtt import Actuator, Preuves, SensorType

from .context import Ctx
from .decisions import AlertSpec, Order, Proposal, evidence, fmt, rule

log = logging.getLogger(__name__)


def _on(ctx: Ctx, actuator: Actuator, texte: str, duree_s: float | None = None) -> Order:
    """Full power: "pwm 100" for a PWM actuator, "on" otherwise."""
    cfg = ctx.act(actuator)
    if cfg is not None and cfg.commande == "pwm":
        return Order(actuator, "pwm", 100.0, duree_s, texte)
    return Order(actuator, "on", None, duree_s, texte)


def _proposal(
    ctx: Ctx,
    rule_id: str,
    explication: str,
    orders: list[Order],
    capteurs=(),
    type_: str = "routine",
    alerte=None,
    emplacements=(),
    version: int = 1,
) -> Proposal:
    consignes = ctx.sp.as_evidence() if ctx.sp else {}
    return Proposal(
        zone=ctx.zone,
        regle=rule(rule_id, version),
        niveau=1,
        type=type_,
        explication=explication,
        orders=orders,
        alerte=alerte,
        emplacements=list(emplacements),
        preuves=Preuves(capteurs=list(capteurs), consignes=consignes),
    )


def _owned(ctx: Ctx, actuator: Actuator, rule_id: str) -> bool:
    """The rule switched the actuator on, long enough ago to switch it off (no short cycle)."""
    cfg = ctx.act(actuator)
    min_on = cfg.marche_min_s if cfg is not None else 0.0
    return (
        ctx.zs.actuator_on(actuator)
        and ctx.zs.owner.get(actuator) == rule_id
        and ctx.since_on(actuator) >= min_on
    )


def _hysteresis(
    ctx: Ctx,
    rule_id: str,
    actuator: Actuator,
    sensor: SensorType,
    value: float,
    on_if_above: float | None,
    off_if_below: float | None,
    unit: str,
    label: str,
) -> list[Proposal]:
    """High (or low with the signs flipped) threshold with hysteresis."""
    if ctx.act(actuator) is None:
        return []
    ev = evidence(ctx.zone, sensor, ctx.reading(sensor))
    if on_if_above is not None and value > on_if_above:
        msg = f"{label} {fmt(value)} {unit} > {fmt(on_if_above)} {unit} → {actuator} on"
        return [_proposal(ctx, rule_id, msg, [_on(ctx, actuator, msg)], [ev])]
    if off_if_below is not None and value < off_if_below and _owned(ctx, actuator, rule_id):
        msg = f"{label} {fmt(value)} {unit} < {fmt(off_if_below)} {unit} → {actuator} off"
        return [_proposal(ctx, rule_id, msg, [Order(actuator, "off", texte=msg)], [ev])]
    return []


def temperature(ctx: Ctx) -> list[Proposal]:
    t = ctx.value(SensorType.TEMPERATURE)
    if t is None or ctx.sp is None:
        return []
    lo, hi = ctx.sp.temperature(ctx.jour)
    h = ctx.gh.cfg.hysteresis.temperature
    out = _hysteresis(
        ctx,
        "climat.temperature.ventilation",
        Actuator.VENTILO,
        SensorType.TEMPERATURE,
        t,
        hi,
        hi - h,
        "°C",
        "T°",
    )
    # Heating: the low threshold, with the signs flipped.
    if ctx.act(Actuator.CHAUFFAGE) is not None:
        ev = evidence(ctx.zone, SensorType.TEMPERATURE, ctx.reading(SensorType.TEMPERATURE))
        rid = "climat.temperature.chauffage"
        if t < lo:
            msg = f"T° {fmt(t)} °C < {fmt(lo)} °C → chauffage on"
            out.append(_proposal(ctx, rid, msg, [_on(ctx, Actuator.CHAUFFAGE, msg)], [ev]))
        elif t > lo + h and _owned(ctx, Actuator.CHAUFFAGE, rid):
            msg = f"T° {fmt(t)} °C > {fmt(lo + h)} °C → chauffage off"
            out.append(
                _proposal(ctx, rid, msg, [Order(Actuator.CHAUFFAGE, "off", texte=msg)], [ev])
            )
    return out


def humidity(ctx: Ctx) -> list[Proposal]:
    hr = ctx.value(SensorType.HUMIDITE)
    if hr is None or ctx.sp is None:
        return []
    lo, hi = ctx.sp.humidite
    h = ctx.gh.cfg.hysteresis.humidite
    t = ctx.value(SensorType.TEMPERATURE)
    t_lo = ctx.sp.temperature(ctx.jour)[0]
    rid = "climat.humidite.ventilation"
    # Ventilating a cold greenhouse to dry it would chill the plants: no start below the
    # minimum temperature, stop below minimum - hysteresis.
    cold_stop = t is not None and t < t_lo - ctx.gh.cfg.hysteresis.temperature
    out = []
    if cold_stop and _owned(ctx, Actuator.VENTILO, rid):
        stop = t_lo - ctx.gh.cfg.hysteresis.temperature
        msg = f"T° {fmt(t)} °C < {fmt(stop)} °C → ventilation d'humidité arrêtée"
        ev = evidence(ctx.zone, SensorType.TEMPERATURE, ctx.reading(SensorType.TEMPERATURE))
        out.append(_proposal(ctx, rid, msg, [Order(Actuator.VENTILO, "off", texte=msg)], [ev]))
    elif t is None or t >= t_lo or (not cold_stop and _owned(ctx, Actuator.VENTILO, rid)):
        out += _hysteresis(
            ctx, rid, Actuator.VENTILO, SensorType.HUMIDITE, hr, hi, hi - h, "%", "HR"
        )

    cfg = ctx.act(Actuator.BRUMISATEUR)
    if cfg is not None and hr < lo and ctx.since_on(Actuator.BRUMISATEUR) >= cfg.delai_min_s:
        ev = evidence(ctx.zone, SensorType.HUMIDITE, ctx.reading(SensorType.HUMIDITE), seuil=lo)
        duree = cfg.duree_s or 60.0
        msg = f"HR {fmt(hr)} % < {fmt(lo)} % → brumisation {duree:g} s"
        out.append(
            _proposal(
                ctx,
                "climat.humidite.brumisation",
                msg,
                [_on(ctx, Actuator.BRUMISATEUR, msg, duree)],
                [ev],
            )
        )
    return out


def _dose_ready(ctx: Ctx, actuator: Actuator, sensor: SensorType) -> bool:
    """A new pulse only once the solution has mixed AND a new measurement was taken."""
    cfg = ctx.act(actuator)
    last = ctx.zs.last_on.get(actuator)
    r = ctx.reading(sensor)
    if cfg is None or r is None:
        return False
    if last is None:
        return True
    mixed = last + timedelta(seconds=(cfg.impulsion_s or 0) + cfg.melange_s)
    return ctx.now >= mixed and r.ts >= mixed


def ph(ctx: Ctx) -> list[Proposal]:
    v = ctx.value(SensorType.PH)
    if v is None or ctx.sp is None or ctx.sp.ph is None or not ctx.zcfg.hydro:
        return []
    lo, hi = ctx.sp.ph
    ev = evidence(ctx.zone, SensorType.PH, ctx.reading(SensorType.PH))
    if v > hi and _dose_ready(ctx, Actuator.POMPE_PH_DOWN, SensorType.PH):
        pulse = ctx.act(Actuator.POMPE_PH_DOWN).impulsion_s or 1.0
        msg = f"pH {fmt(v, 2)} > {fmt(hi, 2)} → impulsion pH− {pulse:g} s"
        return [
            _proposal(
                ctx, "ph.dosage", msg, [Order(Actuator.POMPE_PH_DOWN, "on", None, pulse, msg)], [ev]
            )
        ]
    if v < lo:  # no pH+ pump: report only
        msg = f"pH {fmt(v, 2)} < {fmt(lo, 2)} (pas de pompe pH+)"
        return [
            _proposal(
                ctx,
                "ph.dosage",
                msg,
                [],
                [ev],
                alerte=AlertSpec(
                    "warning",
                    f"{ctx.zone} : {msg}",
                    f"{ctx.zone}/ph.bas",
                    f"{ctx.zone} : pH revenu dans la plage",
                ),
            )
        ]
    return []


def ec(ctx: Ctx) -> list[Proposal]:
    v = ctx.value(SensorType.EC)
    if v is None or ctx.sp is None or ctx.sp.ec is None or not ctx.zcfg.hydro:
        return []
    lo, hi = ctx.sp.ec
    ev = evidence(ctx.zone, SensorType.EC, ctx.reading(SensorType.EC))
    a, b = ctx.act(Actuator.POMPE_NUTRI_A), ctx.act(Actuator.POMPE_NUTRI_B)
    if v < lo and a is not None and _dose_ready(ctx, Actuator.POMPE_NUTRI_A, SensorType.EC):
        msg = f"EC {fmt(v, 2)} < {fmt(lo, 2)} mS/cm → impulsion nutriments A/B"
        orders = [Order(Actuator.POMPE_NUTRI_A, "on", None, a.impulsion_s or 1.0, msg)]
        if b is not None:
            orders.append(Order(Actuator.POMPE_NUTRI_B, "on", None, b.impulsion_s or 1.0, msg))
        return [_proposal(ctx, "ec.nutriments", msg, orders, [ev])]
    if v > hi:
        msg = f"EC {fmt(v, 2)} > {fmt(hi, 2)} mS/cm : ajouter de l'eau claire"
        return [
            _proposal(
                ctx,
                "ec.nutriments",
                msg,
                [],
                [ev],
                alerte=AlertSpec(
                    "warning",
                    f"{ctx.zone} : {msg}",
                    f"{ctx.zone}/ec.haute",
                    f"{ctx.zone} : EC revenue dans la plage",
                ),
            )
        ]
    return []


def light(ctx: Ctx) -> list[Proposal]:
    cfg = ctx.act(Actuator.LED)
    if cfg is None or ctx.sp is None:
        return []
    rid = "lumiere.photoperiode"
    on = ctx.zs.actuator_on(Actuator.LED)
    if not ctx.jour:
        if on:
            msg = f"hors photopériode ({ctx.sp.photoperiode_h:g} h) → LED off"
            return [_proposal(ctx, rid, msg, [Order(Actuator.LED, "off", texte=msg)])]
        return []

    lux = ctx.value(SensorType.LUX)
    k = ctx.gh.cfg.lumiere.lux_vers_ppfd
    state, r = ctx.zs.actuators.get(Actuator.LED), ctx.reading(SensorType.LUX)
    hold = timedelta(seconds=ctx.gh.cfg.lumiere.maintien_s)
    if lux is not None and state is not None and (r.ts <= state.ts or ctx.now - state.ts < hold):
        # The projection extrapolates the current light over the rest of the day: hold each
        # complement decision (sensor noise, clouds), and never use a lux measured before
        # the last LED change.
        return []
    if lux is None or ctx.sp.dli_cible is None:  # no measurement: plain photoperiod
        want, msg, capteurs = True, f"photopériode {ctx.sp.photoperiode_h:g} h → LED on", []
    else:
        led_ppfd = (cfg.ppfd_max or 0) * ctx.zs.actuator_level(Actuator.LED)
        natural = max(0.0, lux * k - led_ppfd)
        end = ctx.window()[1]
        remaining = max(0.0, (end - ctx.local).total_seconds())
        projected = ctx.zs.dli + natural * remaining / 1e6
        target = ctx.sp.dli_cible
        want = projected < (target if on else 0.9 * target)
        verb = "complément LED" if want else "LED inutile"
        msg = (
            f"DLI projeté {fmt(projected)} mol/m² (mesuré {fmt(ctx.zs.dli)}) "
            f"{'<' if want else '≥'} cible {fmt(target)} → {verb}"
        )
        capteurs = [
            evidence(
                ctx.zone,
                SensorType.LUX,
                valeur=ctx.zs.dli,
                unite="mol/m²",
                agregat="dli_jour",
                seuil=target,
            )
        ]
    if want:
        level = ctx.gh.cfg.lumiere.pwm_complement
        order = (
            Order(Actuator.LED, "pwm", level, None, msg)
            if cfg.commande == "pwm"
            else Order(Actuator.LED, "on", texte=msg)
        )
        return [_proposal(ctx, rid, msg, [order], capteurs)]
    if on:
        return [_proposal(ctx, rid, msg, [Order(Actuator.LED, "off", texte=msg)], capteurs)]
    return []


def soil(ctx: Ctx) -> list[Proposal]:
    cfg = ctx.act(Actuator.POMPE_NUTRI)
    if cfg is None or ctx.zcfg.hydro or ctx.since_on(Actuator.POMPE_NUTRI) < cfg.delai_min_s:
        return []
    dry, capteurs = [], []
    for emp in ctx.zs.emplacements(SensorType.HUMIDITE_SOL):
        v = ctx.value(SensorType.HUMIDITE_SOL, emp)
        sp = ctx.gh.emplacement_setpoints(ctx.zone, emp)
        if v is None or sp is None or sp.humidite_sol is None:
            continue
        if v < sp.humidite_sol[0]:
            dry.append(emp)
            capteurs.append(
                evidence(
                    ctx.zone,
                    SensorType.HUMIDITE_SOL,
                    ctx.reading(SensorType.HUMIDITE_SOL, emp),
                    seuil=sp.humidite_sol[0],
                )
            )
    if not dry:
        return []
    duree = cfg.duree_s or 30.0
    vals = ", ".join(
        f"{c.emplacement} {fmt(c.valeur, 0)} % < {fmt(c.seuil, 0)} %" for c in capteurs
    )
    msg = f"sol sec ({vals}) → arrosage {duree:g} s"
    return [
        _proposal(
            ctx,
            "sol.arrosage",
            msg,
            [Order(Actuator.POMPE_NUTRI, "on", None, duree, msg)],
            capteurs,
            emplacements=dry,
        )
    ]


def circulation(ctx: Ctx) -> list[Proposal]:
    cfg = ctx.act(Actuator.POMPE_NUTRI)
    if cfg is None or not ctx.zcfg.hydro or ctx.since_on(Actuator.POMPE_NUTRI) < cfg.delai_min_s:
        return []
    duree = cfg.duree_s or 600.0
    msg = f"cycle de circulation {duree:g} s toutes les {cfg.delai_min_s / 60:g} min"
    return [
        _proposal(
            ctx, "hydro.circulation", msg, [Order(Actuator.POMPE_NUTRI, "on", None, duree, msg)]
        )
    ]


class Presence:
    """Intrusion alert outside the declared ranges; visits inside them are logged."""

    def __init__(self):
        self.visit: dict[str, bool] = {}

    def __call__(self, ctx: Ctx) -> list[Proposal]:
        n = ctx.value(SensorType.PRESENCE)
        if not n:
            self.visit.pop(ctx.zone, None)
            return []
        t = ctx.local.time()
        if any(p.contains(t) for p in ctx.zcfg.presence_autorisee):
            if not self.visit.get(ctx.zone):
                log.info("%s : visite (%d cible(s)) à %s", ctx.zone, n, t.strftime("%H:%M"))
                self.visit[ctx.zone] = True
            return []
        ev = evidence(ctx.zone, SensorType.PRESENCE, ctx.reading(SensorType.PRESENCE))
        msg = f"présence ({n:g} cible(s)) à {t:%H:%M}, hors des plages déclarées : intrusion ?"
        return [
            _proposal(
                ctx,
                "presence.intrusion",
                msg,
                [],
                [ev],
                type_="exceptionnelle",
                alerte=AlertSpec(
                    "warning", f"{ctx.zone} : {msg}", f"{ctx.zone}/presence.intrusion"
                ),
            )
        ]


class Rules:
    """All level 1 rules of a zone, in evaluation order."""

    def __init__(self):
        self.rules = [temperature, humidity, ph, ec, light, soil, circulation, Presence()]

    def evaluate(self, ctx: Ctx) -> list[Proposal]:
        out = []
        for r in self.rules:
            out += r(ctx)
        return out
