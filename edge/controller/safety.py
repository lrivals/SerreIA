"""Level 0, hard limits always active (docs/06 §4) — independent of the rules above.

- `check()`: every order goes through it before being published. Pumps must be bounded in
  time (`duree_s` <= `duree_max_s`, longer orders are shortened), no pump with an empty or
  unknown tank, no misting while somebody is in the greenhouse, no heating above T max,
  no ventilation below T min, no pH- dosing below pH min.
- `watch()`: proposals of the safety level itself — heating off above T max, ventilation
  off below T min, pumps off on an empty tank, misting off on presence, alerts on pH out
  of [4.5, 8], on a muted sensor (no reading for 5 min), on a frozen one (same value for
  30 min) and on an offline node.

The ESP32 firmware enforces its own limits (pump deadline, local empty-tank switch,
degraded mode): this module never replaces them.
"""

from dataclasses import dataclass, replace
from datetime import timedelta

from common.mqtt import Actuator, Preuves, SensorType

from .context import Ctx
from .decisions import AlertSpec, Order, Proposal, evidence, fmt, rule
from .state import GreenhouseState

SOURCE = "safety"
# Noisy measurements: an identical value for `capteur_fige_s` means a frozen sensor.
FROZEN_CHECK = (
    SensorType.TEMPERATURE,
    SensorType.HUMIDITE,
    SensorType.PRESSION,
    SensorType.CO2,
    SensorType.PH,
    SensorType.EC,
)


@dataclass(frozen=True)
class Verdict:
    ok: bool
    order: Order
    limite: str | None = None  # id of the limit that refused or adjusted the order
    note: str | None = None


def check(ctx: Ctx, order: Order) -> Verdict:
    """Refuse or adjust one order. "off" is always allowed."""
    if not order.is_on:
        return Verdict(True, order)
    a = order.actuator
    cfg = ctx.act(a)
    if cfg is None:
        return Verdict(
            False, order, "securite.actionneur_inconnu", f"{a} non déclaré dans {ctx.zone}"
        )
    lim = ctx.gh.cfg.securite
    t = ctx.value(SensorType.TEMPERATURE)

    if a.is_pump:
        if order.duree_s is None:
            return Verdict(False, order, "securite.pompe_sans_duree", f"{a} sans duree_s")
        if ctx.zcfg.cuve:
            level = ctx.value(SensorType.NIVEAU_CUVE)
            if level is None:
                return Verdict(False, order, "securite.cuve_inconnue", "niveau de cuve inconnu")
            if level < lim.niveau_cuve_min:
                return Verdict(
                    False,
                    order,
                    "securite.cuve_vide",
                    f"cuve à {fmt(level, 0)} % < {fmt(lim.niveau_cuve_min, 0)} %",
                )
        if a == Actuator.POMPE_PH_DOWN:
            ph = ctx.value(SensorType.PH)
            if ph is not None and ph < lim.ph_min:
                return Verdict(False, order, "securite.ph_bas", f"pH {fmt(ph, 2)} < {lim.ph_min}")
        if cfg.duree_max_s is not None and order.duree_s > cfg.duree_max_s:
            return Verdict(
                True,
                replace(order, duree_s=cfg.duree_max_s),
                "securite.duree_max",
                f"durée ramenée à {cfg.duree_max_s:g} s",
            )
    if a == Actuator.BRUMISATEUR and (ctx.value(SensorType.PRESENCE) or 0) > 0:
        return Verdict(False, order, "securite.presence", "présence dans la serre")
    if a == Actuator.CHAUFFAGE and t is not None and t >= lim.t_max:
        return Verdict(False, order, "securite.t_max", f"T° {fmt(t)} °C ≥ {lim.t_max:g} °C")
    if a == Actuator.VENTILO and t is not None and t <= lim.t_min:
        return Verdict(False, order, "securite.t_min", f"T° {fmt(t)} °C ≤ {lim.t_min:g} °C")
    return Verdict(True, order)


def _safety(ctx: Ctx, rule_id: str, explication: str, orders=(), alerte=None, capteurs=()):
    return Proposal(
        zone=ctx.zone,
        regle=rule(rule_id),
        niveau=0,
        type="securite",
        origine=SOURCE,
        explication=explication,
        orders=[o for o in orders if ctx.act(o.actuator)],
        alerte=alerte,
        preuves=Preuves(capteurs=list(capteurs)),
    )


def watch_zone(ctx: Ctx) -> list[Proposal]:
    lim = ctx.gh.cfg.securite
    zone, out = ctx.zone, []
    t = ctx.value(SensorType.TEMPERATURE)
    if t is not None and t > lim.t_max:
        ev = evidence(
            zone, SensorType.TEMPERATURE, ctx.reading(SensorType.TEMPERATURE), seuil=lim.t_max
        )
        msg = f"T° {fmt(t)} °C > max {lim.t_max:g} °C → chauffage coupé"
        out.append(
            _safety(
                ctx,
                "securite.t_max",
                msg,
                [Order(Actuator.CHAUFFAGE, "off", texte="T° max")],
                AlertSpec(
                    "critique",
                    f"{zone} : {msg}",
                    f"{zone}/securite.t_max",
                    f"{zone} : T° revenue sous {lim.t_max:g} °C",
                ),
                [ev],
            )
        )
    if t is not None and t < lim.t_min:
        ev = evidence(
            zone, SensorType.TEMPERATURE, ctx.reading(SensorType.TEMPERATURE), seuil=lim.t_min
        )
        msg = f"T° {fmt(t)} °C < min {lim.t_min:g} °C → ventilation coupée"
        out.append(
            _safety(
                ctx,
                "securite.t_min",
                msg,
                [Order(Actuator.VENTILO, "off", texte="T° min")],
                AlertSpec(
                    "critique",
                    f"{zone} : {msg}",
                    f"{zone}/securite.t_min",
                    f"{zone} : T° revenue au-dessus de {lim.t_min:g} °C",
                ),
                [ev],
            )
        )

    ph = ctx.value(SensorType.PH)
    if ph is not None and not lim.ph_min <= ph <= lim.ph_max:
        ev = evidence(zone, SensorType.PH, ctx.reading(SensorType.PH))
        msg = f"pH {fmt(ph, 2)} hors de [{lim.ph_min:g} ; {lim.ph_max:g}]"
        orders = (
            [Order(Actuator.POMPE_PH_DOWN, "off", texte="pH hors limites")]
            if ph < lim.ph_min
            else []
        )
        out.append(
            _safety(
                ctx,
                "securite.ph",
                msg,
                orders,
                AlertSpec(
                    "critique",
                    f"{zone} : {msg}",
                    f"{zone}/securite.ph",
                    f"{zone} : pH revenu dans les limites",
                ),
                [ev],
            )
        )

    if ctx.zcfg.cuve:
        level = ctx.value(SensorType.NIVEAU_CUVE)
        if level is not None and level < lim.niveau_cuve_min:
            pumps = [a for a in Actuator if a.is_pump and ctx.zs.actuator_on(a)]
            ev = evidence(
                zone,
                SensorType.NIVEAU_CUVE,
                ctx.reading(SensorType.NIVEAU_CUVE),
                seuil=lim.niveau_cuve_min,
            )
            msg = f"cuve vide ({fmt(level, 0)} %) → pompes interdites"
            out.append(
                _safety(
                    ctx,
                    "securite.cuve_vide",
                    msg,
                    [Order(a, "off", texte="cuve vide") for a in pumps],
                    AlertSpec(
                        "critique",
                        f"{zone} : {msg}",
                        f"{zone}/securite.cuve_vide",
                        f"{zone} : cuve de nouveau remplie",
                    ),
                    [ev],
                )
            )

    presence = ctx.value(SensorType.PRESENCE)
    if presence and ctx.zs.actuator_on(Actuator.BRUMISATEUR):
        ev = evidence(zone, SensorType.PRESENCE, ctx.reading(SensorType.PRESENCE))
        out.append(
            _safety(
                ctx,
                "securite.presence",
                "présence détectée → brumisation suspendue",
                [Order(Actuator.BRUMISATEUR, "off", texte="présence")],
                None,
                [ev],
            )
        )

    window = timedelta(seconds=lim.capteur_fige_s)
    for sensor in FROZEN_CHECK:
        pts = [v for t, v in ctx.zs.history.get(sensor, ()) if ctx.now - t <= window]
        first = ctx.zs.history.get(sensor)
        if (
            len(pts) >= 10
            and len(set(pts)) == 1
            and first
            and ctx.now - first[0][0] >= window
            and ctx.value(sensor) is not None
        ):
            r = ctx.reading(sensor)
            mins = window.total_seconds() / 60
            msg = f"{zone} : capteur {sensor} de {r.noeud} figé à {pts[0]:g} depuis {mins:.0f} min"
            out.append(
                _safety(
                    ctx,
                    "securite.capteur_fige",
                    msg,
                    (),
                    AlertSpec(
                        "warning",
                        msg,
                        f"{zone}/securite.capteur_fige/{sensor}",
                        f"{zone} : capteur {sensor} de nouveau variable",
                    ),
                )
            )

    for (sensor, emp), r in sorted(
        ctx.zs.readings.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")
    ):
        age = (ctx.now - r.ts).total_seconds()
        if age > lim.capteur_muet_s:
            name = f"{sensor}" + (f" ({emp})" if emp else "")
            key = f"{zone}/securite.capteur_muet/{sensor}/{emp or ''}"
            msg = f"{zone} : capteur {name} de {r.noeud} muet depuis {age / 60:.0f} min"
            out.append(
                _safety(
                    ctx,
                    "securite.capteur_muet",
                    msg,
                    (),
                    AlertSpec("warning", msg, key, f"{zone} : capteur {name} de retour"),
                )
            )
    return out


def watch_nodes(state: GreenhouseState, ctxs: dict[str, Ctx]) -> list[Proposal]:
    """Offline nodes: the alert goes to the zones the node publishes for (or the first)."""
    out = []
    for node, status in sorted(state.nodes.items()):
        if status != "offline":
            continue
        zones = (
            sorted(
                {
                    z
                    for z, zs in state.zones.items()
                    if z in ctxs and any(r.noeud == node for r in zs.readings.values())
                }
            )
            or sorted(ctxs)[:1]
        )
        for z in zones:
            msg = f"nœud {node} hors ligne"
            out.append(
                _safety(
                    ctxs[z],
                    "securite.noeud_offline",
                    msg,
                    (),
                    AlertSpec(
                        "warning",
                        f"{z} : {msg}",
                        f"{z}/securite.offline/{node}",
                        f"{z} : nœud {node} de nouveau en ligne",
                    ),
                )
            )
    return out


def watch(state: GreenhouseState, ctxs: dict[str, Ctx]) -> list[Proposal]:
    out = []
    for ctx in ctxs.values():
        out += watch_zone(ctx)
    return out + watch_nodes(state, ctxs)
