"""Daily consumption estimated from actuator states (docs/09 §5).

    python -m backend.consumption --jour 2026-10-16 [--db URL]

No electrical measurement: energy = Σ puissance_w × state factor (on 1, pwm valeur/100,
off 0) × duration, water = debit_l_h × "on" duration of the pumps, inputs (mL) =
debit_ml_min × "on" duration of the dosing pumps (pH−, nutrients A / B; not counted as
water), LED light = ppfd_max × valeur/100 × duration. The measured light integral comes
from the lux sensor (× the `lux_vers_ppfd` factor of the serre); it includes the LED, so
the natural part is the difference. Days are local days of the serre's time zone.

A TimescaleDB continuous aggregate cannot compute state durations (window functions are
not allowed), hence this job, run every hour by the ingestion and on demand here.
"""

import argparse
import logging
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from common.mqtt import Actuator

from .db.models import Actionneur, ConsommationJour, EtatActionneur, LumiereJour, Mesure, Serre
from .db.session import init_db, insert, make_engine, make_sessions, utc

log = logging.getLogger(__name__)

MAX_GAP = timedelta(minutes=15)  # lux readings further apart are not integrated


@dataclass(frozen=True)
class State:
    ts: datetime
    action: str  # on | off | pwm
    valeur: float | None = None

    @property
    def factor(self) -> float:
        if self.action == "on":
            return 1.0
        if self.action == "pwm":
            return (self.valeur or 0.0) / 100.0
        return 0.0


def day_bounds(jour: date, fuseau: str) -> tuple[datetime, datetime]:
    """UTC bounds of a local day (23 or 25 h on DST change days)."""
    tz = ZoneInfo(fuseau)
    debut = datetime.combine(jour, time(0), tz)
    fin = datetime.combine(jour + timedelta(days=1), time(0), tz)
    return debut.astimezone(UTC), fin.astimezone(UTC)


def state_intervals(
    states: Sequence[State], debut: datetime, fin: datetime
) -> list[tuple[datetime, datetime, float]]:
    """(start, end, factor) over [debut, fin]. `states` sorted by ts; the last state before
    `debut` gives the initial state (unknown before the first state: nothing counted)."""
    out = []
    for cur, nxt in zip(states, [*states[1:], None], strict=False):
        start = max(cur.ts, debut)
        end = min(nxt.ts if nxt else fin, fin)
        if end > start:
            out.append((start, end, cur.factor))
    return out


def weighted_seconds(intervals: Iterable[tuple[datetime, datetime, float]]) -> float:
    return sum((b - a).total_seconds() * f for a, b, f in intervals)


def on_seconds(intervals: Iterable[tuple[datetime, datetime, float]]) -> float:
    return sum((b - a).total_seconds() for a, b, f in intervals if f > 0)


def energy_kwh(puissance_w: float, weighted_s: float) -> float:
    return puissance_w * weighted_s / 3.6e6


def water_l(debit_l_h: float, on_s: float) -> float:
    return debit_l_h * on_s / 3600.0


def inputs_ml(debit_ml_min: float, on_s: float) -> float:
    """Volume of a dosing pump: flow × "on" time (= volume per pulse × number of pulses)."""
    return debit_ml_min * on_s / 60.0


def dli_led(ppfd_max: float, weighted_s: float) -> float:
    """mol/m² from µmol/m²/s × s."""
    return ppfd_max * weighted_s / 1e6


def light_integral(
    readings: Sequence[tuple[datetime, float]],
    debut: datetime,
    fin: datetime,
    lux_vers_ppfd: float,
    max_gap: timedelta = MAX_GAP,
) -> tuple[float, float]:
    """(DLI mol/m², covered seconds) by trapezoids between consecutive lux readings,
    clipped to [debut, fin]; gaps longer than `max_gap` (sensor down) are skipped."""
    total = covered = 0.0
    for (t0, v0), (t1, v1) in zip(readings, readings[1:], strict=False):
        if t1 - t0 > max_gap or t1 <= debut or t0 >= fin:
            continue
        a, b = max(t0, debut), min(t1, fin)
        span = (t1 - t0).total_seconds()

        def at(t: datetime, t0=t0, v0=v0, v1=v1, span=span) -> float:
            return v0 + (v1 - v0) * (t - t0).total_seconds() / span

        dt = (b - a).total_seconds()
        total += (at(a) + at(b)) / 2 * dt
        covered += dt
    return total * lux_vers_ppfd / 1e6, covered


def _states(session: Session, zone: str, actuator: str, debut: datetime, fin: datetime):
    q = select(EtatActionneur).where(
        EtatActionneur.zone == zone, EtatActionneur.actionneur == actuator
    )
    before = session.scalars(
        q.where(EtatActionneur.ts < debut).order_by(EtatActionneur.ts.desc()).limit(1)
    ).all()
    during = session.scalars(
        q.where(EtatActionneur.ts >= debut, EtatActionneur.ts < fin).order_by(EtatActionneur.ts)
    ).all()
    return [State(utc(r.ts), r.action, r.valeur) for r in [*before, *during]]


def compute_day(session: Session, jour: date, now: datetime | None = None) -> dict:
    """Upsert `consommation_jour` and `lumiere_jour` for one local day; the current day is
    counted up to `now`. Returns totals {kwh, litres, ml, cout}. The caller commits."""
    serre = session.scalars(select(Serre)).first()
    if serre is None:
        raise RuntimeError("aucune serre en base : lancer d'abord python -m backend.db.seed")
    debut, fin = day_bounds(jour, serre.fuseau)
    fin = min(fin, now or datetime.now(UTC))
    if fin <= debut:
        return {"kwh": 0.0, "litres": 0.0, "ml": 0.0, "cout": None}
    rows, led_by_zone = [], {}
    for a in session.scalars(select(Actionneur).order_by(Actionneur.id)):
        iv = state_intervals(_states(session, a.zone_id, a.type, debut, fin), debut, fin)
        w = weighted_seconds(iv)
        kwh = energy_kwh(a.puissance_w, w) if a.puissance_w is not None else None
        kind = Actuator(a.type)
        on_s = on_seconds(iv)
        water = kind.is_pump and not kind.is_dosing
        litres = water_l(a.debit_l_h, on_s) if water and a.debit_l_h else None
        ml = inputs_ml(a.debit_ml_min, on_s) if kind.is_dosing and a.debit_ml_min else None
        dli = dli_led(a.ppfd_max, w) if a.type == Actuator.LED and a.ppfd_max else None
        if dli is not None:
            led_by_zone[a.zone_id] = led_by_zone.get(a.zone_id, 0.0) + dli
        cout = kwh * serre.tarif_kwh if kwh is not None and serre.tarif_kwh else None
        rows.append(
            dict(
                jour=jour,
                actionneur_id=a.id,
                zone=a.zone_id,
                type=a.type,
                duree_on_s=w,
                kwh=kwh,
                litres=litres,
                ml=ml,
                dli=dli,
                cout=cout,
            )
        )
    _upsert(session, ConsommationJour, rows, ["jour", "actionneur_id"])

    light = []
    zones = {r["zone"] for r in rows} | set(
        session.scalars(select(Mesure.zone).where(Mesure.type == "lux").distinct())
    )
    for zone in sorted(zones):
        lux = session.execute(
            select(Mesure.ts, Mesure.valeur)
            .where(
                Mesure.zone == zone,
                Mesure.type == "lux",
                Mesure.qualite != "erreur",
                Mesure.ts >= debut - MAX_GAP,
                Mesure.ts <= fin + MAX_GAP,
            )
            .order_by(Mesure.ts)
        ).all()
        total, covered = light_integral(
            [(utc(t), v) for t, v in lux], debut, fin, serre.lux_vers_ppfd
        )
        led = led_by_zone.get(zone, 0.0)
        has_lux = covered > 0
        light.append(
            dict(
                jour=jour,
                zone=zone,
                dli_total=total if has_lux else None,
                dli_led=led,
                dli_naturel=max(0.0, total - led) if has_lux else None,
                couverture=covered / (fin - debut).total_seconds(),
            )
        )
    _upsert(session, LumiereJour, light, ["jour", "zone"])
    kwh = sum(r["kwh"] or 0.0 for r in rows)
    return {
        "kwh": kwh,
        "litres": sum(r["litres"] or 0.0 for r in rows),
        "ml": sum(r["ml"] or 0.0 for r in rows),
        "cout": kwh * serre.tarif_kwh if serre.tarif_kwh else None,
    }


PERIODES = {"jour": 1, "semaine": 7, "mois": 30}


def _r(v: float | None, n: int = 3) -> float | None:
    return round(v, n) if v is not None else None


def summary(
    session: Session,
    periode: str = "jour",
    zone: str | None = None,
    jour: date | None = None,
    now: datetime | None = None,
) -> dict:
    """Consumption over the `periode` (jour | semaine | mois: 1, 7, 30 local days) ending
    on `jour` (default: today, counted up to `now`): totals, per actuator, per day (one
    entry per actuator, for the stacked charts of the UI) and light integrals."""
    now = now or datetime.now(UTC)
    serre = session.scalars(select(Serre)).first()
    if serre is None:
        raise RuntimeError("aucune serre en base : lancer d'abord python -m backend.db.seed")
    today = now.astimezone(ZoneInfo(serre.fuseau)).date()
    last = min(jour or today, today)
    jours = [last - timedelta(days=i) for i in range(PERIODES[periode] - 1, -1, -1)]
    if last == today:  # the current day, up to now (the ingestion runs it every hour)
        compute_day(session, today, now)
    q = select(ConsommationJour).where(ConsommationJour.jour.in_(jours))
    if zone:
        q = q.where(ConsommationJour.zone == zone)
    tot: dict[str, dict] = defaultdict(lambda: defaultdict(float))
    days: dict[date, dict[str, dict]] = {j: {} for j in jours}
    for r in session.scalars(q.order_by(ConsommationJour.jour, ConsommationJour.actionneur_id)):
        t = tot[r.actionneur_id]
        t["zone"], t["type"] = r.zone, r.type  # type: ignore[assignment]
        t["heures_on"] += r.duree_on_s / 3600
        for k in ("kwh", "litres", "ml", "cout", "dli"):
            if getattr(r, k) is not None:
                t[k] += getattr(r, k)
        days[r.jour][r.actionneur_id] = dict(
            zone=r.zone, type=r.type, heures_on=_r(r.duree_on_s / 3600),
            kwh=_r(r.kwh), litres=_r(r.litres), ml=_r(r.ml), cout=_r(r.cout),
        )  # fmt: skip
    lq = select(LumiereJour).where(LumiereJour.jour.in_(jours)).order_by(LumiereJour.jour)
    if zone:
        lq = lq.where(LumiereJour.zone == zone)
    lumiere = [
        dict(jour=r.jour, zone=r.zone, dli_total=_r(r.dli_total), dli_led=_r(r.dli_led),
             dli_naturel=_r(r.dli_naturel), couverture=_r(r.couverture))
        for r in session.scalars(lq)
    ]  # fmt: skip
    actionneurs = {k: {x: _r(y) if isinstance(y, float) else y for x, y in v.items()}
                   for k, v in sorted(tot.items())}  # fmt: skip
    return dict(
        periode=periode,
        du=jours[0],
        au=last,
        jour_en_cours=last == today,
        totaux={
            k: _r(sum(v.get(k, 0.0) for v in tot.values())) for k in ("kwh", "litres", "ml", "cout")
        },
        tarif_kwh=serre.tarif_kwh,
        actionneurs=actionneurs,
        par_jour=[
            dict(
                jour=j,
                totaux={
                    k: _r(sum(a[k] or 0.0 for a in acts.values()))
                    for k in ("kwh", "litres", "ml", "cout")
                },
                actionneurs=acts,
            )
            for j, acts in days.items()
        ],  # fmt: skip
        lumiere=lumiere,
        note="estimation à partir des états des actionneurs (pas de compteur)",
    )


def _upsert(session: Session, model, rows: list[dict], keys: list[str]) -> None:
    if not rows:
        return
    stmt = insert(session, model.__table__)
    stmt = stmt.on_conflict_do_update(
        index_elements=keys, set_={c: stmt.excluded[c] for c in rows[0] if c not in keys}
    )
    session.execute(stmt, rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--jour", type=date.fromisoformat, default=date.today())
    parser.add_argument("--db", help="URL SQLAlchemy (défaut : $SERREIA_DB ou le compose)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    engine = make_engine(args.db)
    init_db(engine)
    with make_sessions(engine).begin() as session:
        totals = compute_day(session, args.jour)
        for r in session.scalars(
            select(ConsommationJour).where(ConsommationJour.jour == args.jour)
        ):
            log.info(
                "%-14s %-14s on %7.0f s  %s kWh  %s L  %s mL  %s DLI",
                r.actionneur_id,
                r.type,
                r.duree_on_s,
                _fmt(r.kwh),
                _fmt(r.litres),
                _fmt(r.ml),
                _fmt(r.dli),
            )
        for r in session.scalars(select(LumiereJour).where(LumiereJour.jour == args.jour)):
            log.info(
                "%s lumière : DLI total %s (LED %s, naturel %s), couverture %.0f %%",
                r.zone,
                _fmt(r.dli_total),
                _fmt(r.dli_led),
                _fmt(r.dli_naturel),
                100 * r.couverture,
            )
    log.info(
        "%s : %.3f kWh, %.1f L, %.0f mL d'intrants, coût %s €",
        args.jour,
        totals["kwh"],
        totals["litres"],
        totals["ml"],
        _fmt(totals["cout"]),
    )


def _fmt(v: float | None) -> str:
    return "—" if v is None else f"{v:.3f}"


if __name__ == "__main__":
    main()
