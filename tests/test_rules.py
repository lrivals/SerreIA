"""Level 1 rules (docs/06 §4): hysteresis, dosing pulses, watering, light, intrusion."""

import pytest

from common.mqtt import Actuator
from edge.controller import rules
from edge.controller.state import GreenhouseState

from .controller_utils import NIGHT, NOON, ctx, feed, greenhouse, minutes, set_actuator


@pytest.fixture
def gh():
    return greenhouse()


def ids(props):
    return {p.regle.id: p for p in props}


def test_temperature_hysteresis_and_ownership(gh):
    s = GreenhouseState()
    feed(s, "z1", "temperature", 27.5, NOON)  # z1 day: [21, 27]
    p = ids(rules.temperature(ctx(gh, s, "z1", NOON)))["climat.temperature.ventilation"]
    assert p.orders[0].actuator == Actuator.VENTILO and p.orders[0].action == "pwm"
    assert p.preuves.capteurs[0].valeur == 27.5 and p.preuves.consignes["humidite"] == (55, 70)

    set_actuator(s, "z1", "ventilo", "pwm", NOON, 100)
    z = s.zone("z1")
    z.owner["ventilo"], z.last_on["ventilo"] = "climat.temperature.ventilation", NOON
    t = NOON + minutes(10)
    feed(s, "z1", "temperature", 26.5, t)  # inside the band: keep
    assert rules.temperature(ctx(gh, s, "z1", t)) == []
    feed(s, "z1", "temperature", 25.9, t)
    off = rules.temperature(ctx(gh, s, "z1", t))
    assert off[0].orders[0].action == "off"
    z.owner["ventilo"] = "climat.humidite.ventilation"  # switched on by another rule
    assert rules.temperature(ctx(gh, s, "z1", t)) == []


def test_minimal_on_time(gh):
    s = GreenhouseState()
    set_actuator(s, "z1", "chauffage", "on", NOON)
    z = s.zone("z1")
    z.owner["chauffage"], z.last_on["chauffage"] = "climat.temperature.chauffage", NOON
    feed(s, "z1", "temperature", 23, NOON + minutes(2))
    assert rules.temperature(ctx(gh, s, "z1", NOON + minutes(2))) == []  # < marche_min_s
    feed(s, "z1", "temperature", 23, NOON + minutes(6))
    assert rules.temperature(ctx(gh, s, "z1", NOON + minutes(6)))[0].orders[0].action == "off"


def test_night_setpoints_and_heating(gh):
    s = GreenhouseState()
    feed(s, "z1", "temperature", 15.5, NIGHT)  # night: [16, 19]
    c = ctx(gh, s, "z1", NIGHT)
    assert not c.jour
    p = ids(rules.temperature(c))["climat.temperature.chauffage"]
    assert p.orders[0].action == "on"


def test_misting_respects_delay(gh):
    s = GreenhouseState()
    feed(s, "z1", "humidite", 45, NOON)
    feed(s, "z1", "temperature", 24, NOON)
    p = ids(rules.humidity(ctx(gh, s, "z1", NOON)))["climat.humidite.brumisation"]
    assert p.orders[0].duree_s == 60
    s.zone("z1").last_on["brumisateur"] = NOON
    t = NOON + minutes(5)
    feed(s, "z1", "humidite", 45, t)
    assert "climat.humidite.brumisation" not in ids(rules.humidity(ctx(gh, s, "z1", t)))


def test_ph_pulse_then_wait_for_mixing_and_new_measure(gh):
    s = GreenhouseState()
    feed(s, "z2", "ph", 6.6, NOON, node="esp32-03")  # laitue: [5.6, 6.2]
    p = rules.ph(ctx(gh, s, "z2", NOON))[0]
    assert p.orders[0].actuator == Actuator.POMPE_PH_DOWN and p.orders[0].duree_s == 2
    s.zone("z2").last_on["pompe_ph_down"] = NOON
    t = NOON + minutes(5)
    feed(s, "z2", "ph", 6.5, t, node="esp32-03")
    assert rules.ph(ctx(gh, s, "z2", t)) == []  # mixing (600 s)
    t = NOON + minutes(11)
    assert rules.ph(ctx(gh, s, "z2", t)) == []  # mixed but no measure since: wait
    feed(s, "z2", "ph", 6.4, t, node="esp32-03")
    assert rules.ph(ctx(gh, s, "z2", t))[0].orders
    feed(s, "z2", "ph", 5.3, t, node="esp32-03")
    low = rules.ph(ctx(gh, s, "z2", t))[0]
    assert not low.orders and low.alerte.niveau == "warning"  # no pH+ pump
    feed(s, "z1", "ph", 7.5, t)
    assert rules.ph(ctx(gh, s, "z1", t)) == []  # soil zone: no dosing


def test_ec_doses_a_and_b(gh):
    s = GreenhouseState()
    feed(s, "z2", "ec", 0.8, NOON, node="esp32-03")
    p = rules.ec(ctx(gh, s, "z2", NOON))[0]
    assert [o.actuator for o in p.orders] == [Actuator.POMPE_NUTRI_A, Actuator.POMPE_NUTRI_B]
    feed(s, "z2", "ec", 2.0, NOON, node="esp32-03")
    assert "eau claire" in rules.ec(ctx(gh, s, "z2", NOON))[0].alerte.message


def test_soil_watering_per_emplacement_with_delay(gh):
    s = GreenhouseState()
    feed(s, "z1", "humidite_sol", 38, NOON, node="esp32-02", emplacement="z1-A1")  # min 45
    feed(s, "z1", "humidite_sol", 50, NOON, node="esp32-02", emplacement="z1-A2")
    p = rules.soil(ctx(gh, s, "z1", NOON))[0]
    assert p.emplacements == ["z1-A1"] and p.orders[0].duree_s == 45
    assert p.preuves.capteurs[0].emplacement == "z1-A1"
    s.zone("z1").last_on["pompe_nutri"] = NOON
    assert rules.soil(ctx(gh, s, "z1", NOON + minutes(30))) == []  # delai_min_s 3600


def test_light_photoperiod_and_complement(gh):
    s = GreenhouseState()
    c = ctx(gh, s, "z1", NOON)
    assert rules.light(c)[0].orders[0].action == "pwm"  # no lux sensor: plain photoperiod
    feed(s, "z1", "lux", 60000, NOON)  # bright sun: 1110 µmol/m²/s for the rest of the day
    assert rules.light(ctx(gh, s, "z1", NOON)) == []
    s2 = GreenhouseState()
    feed(s2, "z1", "lux", 2000, NOON)  # overcast
    assert rules.light(ctx(gh, s2, "z1", NOON))[0].orders[0].action == "pwm"
    set_actuator(s, "z1", "led", "pwm", NIGHT, 100)
    assert rules.light(ctx(gh, s, "z1", NIGHT))[0].orders[0].action == "off"  # outside


def test_presence_intrusion_at_night_only(gh):
    s = GreenhouseState()
    feed(s, "z1", "presence", 1, NIGHT)
    p = rules.Presence()(ctx(gh, s, "z1", NIGHT))[0]
    assert p.alerte.niveau == "warning" and "intrusion" in p.alerte.message
    feed(s, "z1", "presence", 2, NOON)
    assert rules.Presence()(ctx(gh, s, "z1", NOON)) == []  # a visit: logged only


def test_hydro_circulation_cycle(gh):
    s = GreenhouseState()
    p = rules.circulation(ctx(gh, s, "z2", NOON))[0]
    assert p.orders[0].duree_s == 900
    s.zone("z2").last_on["pompe_nutri"] = NOON
    assert rules.circulation(ctx(gh, s, "z2", NOON + minutes(20))) == []
    assert rules.circulation(ctx(gh, s, "z2", NOON + minutes(31)))
    assert rules.circulation(ctx(gh, s, "z1", NOON)) == []


def test_no_circulation_cycles_in_dwc(gh):
    from edge.controller.config import Greenhouse

    raw = gh.cfg.model_dump()
    raw["zones"][1]["emplacements"][0]["mode_culture"] = "hydro_dwc"
    dwc = Greenhouse(type(gh.cfg).model_validate(raw), gh.recipes, gh.especes)
    assert rules.circulation(ctx(dwc, GreenhouseState(), "z2", NOON)) == []  # immersed roots
