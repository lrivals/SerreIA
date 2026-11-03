"""Level 1, rules and regulators (docs/06 §4), each with a stable and versioned id.

| Rule id | Behaviour |
|---|---|
| `climat.temperature.ventilation` | T > max of the recipe → fan on; off below max − hysteresis |
| `climat.temperature.chauffage` | T < min → heating on; off above min + hysteresis |
| `climat.humidite.ventilation` | HR > max or VPD < min → fan on (not when T < min) ¹ |
| `climat.humidite.brumisation` | HR < min → misting `duree_s`, every `delai_min_s` at most ² |
| `ph.dosage` | pH > max → one pH− pulse, wait `melange_s`, re-measure, never continuous |
| `ec.nutriments` | EC < min → one pulse of A and of B, same logic; EC > max → alert |
| `ec.drainage` | drainage EC > max, or drainage − applied EC beyond ± 1 mS/cm → alert |
| `hydro.temperature_solution` | nutrient solution outside `temp_racines` → alert (no actuator) |
| `lumiere.photoperiode` | LEDs only inside the photoperiod; with lux + DLI target: complement ³ |
| `sol.arrosage` | soil of an emplacement < min of its recipe → watering, every `delai_min_s` |
| `hydro.circulation` | hydro zone, except DWC: pump cycles of `duree_s` every `delai_min_s` |
| `presence.intrusion` | presence outside the declared ranges (night) → alert; inside: logged |

¹ off below max − hysteresis, once the VPD is back above its min + 0.1 kPa.
² only when the VPD is above the max of the recipe (when it has one), never below its min,
never at night unless the recipe sets `brumisation_nuit`.
³ none when the stage sets `complement_led: false`, or when the measured DLI is above
`dli_max` (info alert, docs/22 L1).

Rules are stateless and evaluated at every tick: they return what they want and the
controller only publishes what differs from the real actuator state (`etat/`). An "off"
is only proposed by the rule that switched the actuator on (`ZoneState.owner`).

The VPD (docs/22 L4, `psychro.py`) constrains the humidity actuators but never drives
them alone: the same VPD is 15 °C at 50 % or 34 °C at 84 % (`2018-shamshiri#008.0`).
"""

import logging
from datetime import timedelta

from common.mqtt import Actuator, Preuves, SensorType

from .config import HYDRO
from .context import Ctx
from .decisions import AlertSpec, Order, Proposal, evidence, fmt, rule
from .psychro import vpd

log = logging.getLogger(__name__)

VPD_HYSTERESIS = 0.1  # kPa
EC_ECART_MAX = 1.0  # mS/cm, drainage − applied (`1990-hochmuth#014.1`)
TEMP_RACINES_HYSTERESIS = 0.5  # °C


def zone_vpd(ctx: Ctx) -> float | None:
    """VPD (kPa) of the zone air, from the fresh T° and HR; None when one is missing."""
    t, hr = ctx.value(SensorType.TEMPERATURE), ctx.value(SensorType.HUMIDITE)
    return None if t is None or hr is None else vpd(t, hr)


def vpd_evidence(ctx: Ctx, v: float, seuil: float | None = None):
    return evidence(
        ctx.zone, SensorType.HUMIDITE, valeur=v, unite="kPa", agregat="vpd", seuil=seuil
    )


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
    version: int = 1,
) -> list[Proposal]:
    """High (or low with the signs flipped) threshold with hysteresis."""
    if ctx.act(actuator) is None:
        return []
    ev = evidence(ctx.zone, sensor, ctx.reading(sensor))
    if on_if_above is not None and value > on_if_above:
        msg = f"{label} {fmt(value)} {unit} > {fmt(on_if_above)} {unit} → {actuator} on"
        return [_proposal(ctx, rule_id, msg, [_on(ctx, actuator, msg)], [ev], version=version)]
    if off_if_below is not None and value < off_if_below and _owned(ctx, actuator, rule_id):
        msg = f"{label} {fmt(value)} {unit} < {fmt(off_if_below)} {unit} → {actuator} off"
        orders = [Order(actuator, "off", texte=msg)]
        return [_proposal(ctx, rule_id, msg, orders, [ev], version=version)]
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
        orders = [Order(Actuator.VENTILO, "off", texte=msg)]
        out.append(_proposal(ctx, rid, msg, orders, [ev], version=2))
    elif t is None or t >= t_lo or (not cold_stop and _owned(ctx, Actuator.VENTILO, rid)):
        props = _hysteresis(
            ctx, rid, Actuator.VENTILO, SensorType.HUMIDITE, hr, hi, hi - h, "%", "HR", version=2
        )
        v, vlo = zone_vpd(ctx), (ctx.sp.vpd or (None, None))[0]
        if v is not None and vlo is not None:
            if v < vlo + VPD_HYSTERESIS:  # still too humid by the VPD: keep the fan on
                props = [p for p in props if p.orders[0].action != "off"]
            if v < vlo and not props and ctx.act(Actuator.VENTILO) is not None:
                if not ctx.zs.actuator_on(Actuator.VENTILO):
                    msg = f"VPD {fmt(v, 2)} kPa < {fmt(vlo, 2)} kPa → ventilo on"
                    ev = [
                        evidence(ctx.zone, SensorType.HUMIDITE, ctx.reading(SensorType.HUMIDITE)),
                        vpd_evidence(ctx, v, vlo),
                    ]
                    props = [
                        _proposal(ctx, rid, msg, [_on(ctx, Actuator.VENTILO, msg)], ev, version=2)
                    ]
        out += props
    out += _misting(ctx, hr, lo)
    return out


def _misting(ctx: Ctx, hr: float, lo: float) -> list[Proposal]:
    """Misting under the HR min, constrained by the VPD (docs/22 L4) and never at night
    unless the recipe allows it (docs/22 L8: night wetness favours Botrytis)."""
    cfg = ctx.act(Actuator.BRUMISATEUR)
    if cfg is None or hr >= lo or ctx.since_on(Actuator.BRUMISATEUR) < cfg.delai_min_s:
        return []
    if not ctx.jour and not ctx.sp.brumisation_nuit:
        return []
    capteurs = [evidence(ctx.zone, SensorType.HUMIDITE, ctx.reading(SensorType.HUMIDITE), seuil=lo)]
    v, (vlo, vhi) = zone_vpd(ctx), ctx.sp.vpd or (None, None)
    if v is not None and vhi is not None:
        if v <= vhi:  # dry by the HR, not by the VPD: the plants do not need water vapour
            return []
        capteurs.append(vpd_evidence(ctx, v, vhi))
    elif v is not None and vlo is not None and v < vlo:
        return []
    duree = cfg.duree_s or 60.0
    msg = f"HR {fmt(hr)} % < {fmt(lo)} % → brumisation {duree:g} s"
    if v is not None and vhi is not None:
        msg = f"HR {fmt(hr)} % < {fmt(lo)} %, VPD {fmt(v, 2)} kPa > {fmt(vhi, 2)} kPa → " + (
            f"brumisation {duree:g} s"
        )
    return [
        _proposal(
            ctx,
            "climat.humidite.brumisation",
            msg,
            [_on(ctx, Actuator.BRUMISATEUR, msg, duree)],
            capteurs,
            version=2,
        )
    ]


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


def ec_drainage(ctx: Ctx) -> list[Proposal]:
    """Drainage EC (docs/22 L9): the root zone is judged by the drained solution, the
    applied one is only a means (`2018-savvas#025.0`). Alerts only."""
    v = ctx.value(SensorType.EC_DRAINAGE)
    if v is None or ctx.sp is None:
        return []
    ev = [evidence(ctx.zone, SensorType.EC_DRAINAGE, ctx.reading(SensorType.EC_DRAINAGE))]
    applied = ctx.value(SensorType.EC)
    if ctx.sp.ec_drainage is not None and v > ctx.sp.ec_drainage[1]:
        hi = ctx.sp.ec_drainage[1]
        msg = (
            f"EC drainage {fmt(v, 2)} > {fmt(hi, 2)} mS/cm : lessiver ou augmenter la "
            "fraction drainée"
        )
        key = "ec_drainage.haute"
    elif applied is not None and abs(v - applied) > EC_ECART_MAX:
        ev.append(evidence(ctx.zone, SensorType.EC, ctx.reading(SensorType.EC)))
        msg = (
            f"EC drainage {fmt(v, 2)} − EC apport {fmt(applied, 2)} mS/cm hors de "
            f"± {fmt(EC_ECART_MAX)} : vérifier la solution et la fraction drainée"
        )
        key = "ec_drainage.ecart"
    else:
        return []
    return [
        _proposal(
            ctx,
            "ec.drainage",
            msg,
            [],
            ev,
            alerte=AlertSpec(
                "warning",
                f"{ctx.zone} : {msg}",
                f"{ctx.zone}/{key}",
                f"{ctx.zone} : EC de drainage revenue dans la plage",
            ),
        )
    ]


class SolutionTemperature:
    """Nutrient solution temperature against `temp_racines` (docs/22 L3). No actuator heats
    or cools the tank: alert only. Warm solution: less dissolved O₂, Fusarium favoured
    above ~25 °C; cold: growth slowed, Pythium favoured at 15–20 °C. The alert holds until
    the solution is back inside the range by `TEMP_RACINES_HYSTERESIS` (no flapping)."""

    def __init__(self):
        self.side: dict[str, str] = {}  # zone -> "froide" / "chaude" while the alert holds

    def __call__(self, ctx: Ctx) -> list[Proposal]:
        v = ctx.value(SensorType.TEMP_EAU)
        if v is None or ctx.sp is None or ctx.sp.temp_racines is None:
            self.side.pop(ctx.zone, None)
            return []
        lo, hi = ctx.sp.temp_racines
        h = TEMP_RACINES_HYSTERESIS if ctx.zone in self.side else 0.0
        if v < lo + h:
            key, sens, seuil = "froide", "<", lo
        elif v > hi - h:
            key, sens, seuil = "chaude", ">", hi
        else:
            self.side.pop(ctx.zone, None)
            return []
        if ctx.zone in self.side and self.side[ctx.zone] != key:
            key = self.side[ctx.zone]  # narrow range: keep the side of the open alert
            sens, seuil = ("<", lo) if key == "froide" else (">", hi)
        self.side[ctx.zone] = key
        msg = f"solution {fmt(v)} °C {sens} {fmt(seuil)} °C (consigne racines)"
        if (v >= lo and key == "froide") or (v <= hi and key == "chaude"):
            msg = f"solution {fmt(v)} °C, pas encore revenue dans {fmt(lo)}–{fmt(hi)} °C"
        ev = evidence(ctx.zone, SensorType.TEMP_EAU, ctx.reading(SensorType.TEMP_EAU))
        return [
            _proposal(
                ctx,
                "hydro.temperature_solution",
                msg,
                [],
                [ev],
                alerte=AlertSpec(
                    "warning",
                    f"{ctx.zone} : solution {key} ({msg})",
                    f"{ctx.zone}/hydro.solution_{key}",
                    f"{ctx.zone} : T° de la solution revenue dans la plage",
                ),
            )
        ]


def light(ctx: Ctx) -> list[Proposal]:
    cfg = ctx.act(Actuator.LED)
    if cfg is None or ctx.sp is None:
        return []
    rid = "lumiere.photoperiode"
    on = ctx.zs.actuator_on(Actuator.LED)
    if not ctx.jour:
        if on:
            msg = f"hors photopériode ({ctx.sp.photoperiode_h:g} h) → LED off"
            off = [Order(Actuator.LED, "off", texte=msg)]
            return [_proposal(ctx, rid, msg, off, version=2)]
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
    alerte, dli_max = None, ctx.sp.dli_max
    if lux is None or ctx.sp.dli_cible is None or not ctx.sp.complement_led:
        # no measurement, or no complement for this stage (docs/22 L15): plain photoperiod
        want, msg, capteurs = True, f"photopériode {ctx.sp.photoperiode_h:g} h → LED on", []
        if not ctx.sp.complement_led:
            msg += " (sans complément au stade juvénile)"
    elif dli_max is not None and ctx.zs.dli > dli_max:
        # docs/22 L1: above the tipburn threshold, no LED complement at all
        want = False
        msg = f"DLI mesuré {fmt(ctx.zs.dli, 2)} > max {fmt(dli_max)} mol/m² → aucun complément LED"
        capteurs = [
            evidence(ctx.zone, SensorType.LUX, valeur=ctx.zs.dli, unite="mol/m²",
                     agregat="dli_jour", seuil=dli_max)
        ]  # fmt: skip
        alerte = AlertSpec(
            "info",
            f"{ctx.zone} : DLI {fmt(ctx.zs.dli, 2)} mol/m² au-dessus du maximum {fmt(dli_max)}",
            f"{ctx.zone}/lumiere.dli_max",
        )
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
        return [_proposal(ctx, rid, msg, [order], capteurs, version=2)]
    if on:
        off = [Order(Actuator.LED, "off", texte=msg)]
        return [_proposal(ctx, rid, msg, off, capteurs, alerte=alerte, version=2)]
    if alerte is not None:
        return [_proposal(ctx, rid, msg, [], capteurs, alerte=alerte, version=2)]
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
    if ctx.zcfg.modes & set(HYDRO) <= {"hydro_dwc"}:  # DWC: immersed roots, no cycles
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
        self.rules = [
            temperature,
            humidity,
            ph,
            ec,
            ec_drainage,
            SolutionTemperature(),
            light,
            soil,
            circulation,
            Presence(),
        ]

    def evaluate(self, ctx: Ctx) -> list[Proposal]:
        out = []
        for r in self.rules:
            out += r(ctx)
        return out
