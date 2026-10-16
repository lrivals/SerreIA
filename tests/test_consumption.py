"""Daily consumption estimated from actuator states (docs/09 §5)."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from backend.consumption import (
    State,
    compute_day,
    day_bounds,
    dli_led,
    energy_kwh,
    light_integral,
    on_seconds,
    state_intervals,
    water_l,
    weighted_seconds,
)
from backend.db import models as m

from .backend_utils import seeded_db

DAY = date(2026, 7, 15)
MIDNIGHT = datetime(2026, 7, 14, 22, 0, tzinfo=UTC)  # 00:00 Europe/Paris (summer time)


def h(n: float) -> datetime:
    return MIDNIGHT + timedelta(hours=n)


def test_day_bounds_follow_the_time_zone():
    assert day_bounds(DAY, "Europe/Paris") == (MIDNIGHT, MIDNIGHT + timedelta(days=1))
    debut, fin = day_bounds(date(2026, 10, 25), "Europe/Paris")  # back to winter time
    assert fin - debut == timedelta(hours=25)


def test_led_pwm_energy_and_light():
    states = [State(h(6), "pwm", 50), State(h(8), "off")]
    iv = state_intervals(states, *day_bounds(DAY, "Europe/Paris"))
    w = weighted_seconds(iv)
    assert w == pytest.approx(3600)
    assert energy_kwh(240, w) == pytest.approx(0.24)
    assert dli_led(450, w) == pytest.approx(1.62)


def test_state_before_midnight_is_cut_at_the_day_start():
    states = [State(h(-1), "on"), State(h(1), "off"), State(h(23), "on")]  # on until the end
    iv = state_intervals(states, *day_bounds(DAY, "Europe/Paris"))
    assert on_seconds(iv) == pytest.approx(2 * 3600)
    assert state_intervals([], MIDNIGHT, h(24)) == []
    assert state_intervals([State(h(30), "on")], MIDNIGHT, h(24)) == []


def test_pump_water():
    iv = state_intervals(
        [State(h(7), "on"), State(h(7) + timedelta(seconds=45), "off")],
        *(day_bounds(DAY, "Europe/Paris")),
    )
    assert water_l(120, on_seconds(iv)) == pytest.approx(1.5)


def test_light_integral_skips_gaps_and_clips():
    lux = [(h(10), 10000.0), (h(11), 10000.0), (h(12), 30000.0), (h(14), 30000.0)]
    total, covered = light_integral(lux, MIDNIGHT, h(24), 0.0185, max_gap=timedelta(hours=1))
    # 10 → 11 h at 10 klx and 11 → 12 h ramp to 30 klx; 12 → 14 h is a gap (sensor down).
    expected = (10000 * 3600 + 20000 * 3600) * 0.0185 / 1e6
    assert total == pytest.approx(expected) and covered == 7200
    half, _ = light_integral(lux, MIDNIGHT, h(10.5), 0.0185, max_gap=timedelta(hours=1))
    assert half == pytest.approx(10000 * 1800 * 0.0185 / 1e6)


def etat(zone, actuator, ts, action, valeur=None):
    return m.EtatActionneur(ts=ts, zone=zone, actionneur=actuator, action=action, valeur=valeur)


def test_compute_day_writes_the_tables():
    _, sessions = seeded_db()
    with sessions.begin() as s:
        s.add_all(
            [
                etat("z1", "led", h(-2), "off"),
                etat("z1", "led", h(6), "pwm", 50),
                etat("z1", "led", h(8), "off"),
                etat("z1", "pompe_nutri", h(7), "on"),
                etat("z1", "pompe_nutri", h(7) + timedelta(seconds=45), "off"),
                etat("z1", "chauffage", h(20), "on"),  # still on at `now`
            ]
        )
        for i in range(0, 25 * 6):  # constant 10 klx every 10 min
            s.add(
                m.Mesure(
                    ts=h(i / 6),
                    capteur_id="esp32-01-lux",
                    zone="z1",
                    type="lux",
                    noeud="esp32-01",
                    valeur=10000.0,
                    unite="lx",
                    qualite="ok",
                )
            )
    with sessions.begin() as s:
        totals = compute_day(s, DAY, now=h(22))
    with sessions() as s:
        rows = {r.actionneur_id: r for r in s.scalars(select(m.ConsommationJour))}
        light = {r.zone: r for r in s.scalars(select(m.LumiereJour))}
    assert rows["led-z1"].kwh == pytest.approx(0.24) and rows["led-z1"].dli == pytest.approx(1.62)
    assert rows["arrosage-z1"].litres == pytest.approx(1.5)
    assert rows["chauffage-z1"].kwh == pytest.approx(1500 * 2 / 1000)  # 20 h → now (22 h)
    assert rows["ventilo-z1"].duree_on_s == 0  # no state received: nothing counted
    assert rows["ph-down-z2"].kwh is None  # no declared power
    assert rows["led-z1"].cout == pytest.approx(0.24 * 0.25)
    expected_kwh = 0.24 + 20 * 45 / 3.6e6 + 3.0
    assert totals["kwh"] == pytest.approx(expected_kwh)
    assert totals["cout"] == pytest.approx(expected_kwh * 0.25)
    z1 = light["z1"]
    assert z1.dli_total == pytest.approx(10000 * 0.0185 * 22 * 3600 / 1e6)
    assert z1.dli_led == pytest.approx(1.62)
    assert z1.dli_naturel == pytest.approx(z1.dli_total - 1.62)
    assert z1.couverture == pytest.approx(1.0)
    assert light["z2"].dli_total is None and light["z2"].couverture == 0

    with sessions.begin() as s:  # recomputing later in the day updates the rows
        compute_day(s, DAY, now=h(23))
    with sessions() as s:
        assert s.get(m.ConsommationJour, (DAY, "chauffage-z1")).kwh == pytest.approx(4.5)
