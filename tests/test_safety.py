"""Level 0 safety (docs/06 §4): order checks and watch."""

import pytest

from common.mqtt import Actuator
from edge.controller import safety
from edge.controller.decisions import Order
from edge.controller.state import GreenhouseState

from .controller_utils import NOON, ctx, feed, greenhouse, minutes, set_actuator


@pytest.fixture
def gh():
    return greenhouse()


def check(gh, state, zone, order, now=NOON):
    return safety.check(ctx(gh, state, zone, now), order)


def test_pump_without_duration_or_too_long(gh):
    s = GreenhouseState()
    feed(s, "z2", "niveau_cuve", 80, NOON)
    v = check(gh, s, "z2", Order(Actuator.POMPE_PH_DOWN, "on"))
    assert not v.ok and v.limite == "securite.pompe_sans_duree"
    v = check(gh, s, "z2", Order(Actuator.POMPE_PH_DOWN, "on", duree_s=60))
    assert v.ok and v.order.duree_s == 10 and v.limite == "securite.duree_max"


def test_empty_or_unknown_tank_forbids_pumps(gh):
    s = GreenhouseState()
    order = Order(Actuator.POMPE_NUTRI, "on", duree_s=60)
    assert check(gh, s, "z2", order).limite == "securite.cuve_inconnue"
    feed(s, "z2", "niveau_cuve", 4, NOON)
    assert check(gh, s, "z2", order).limite == "securite.cuve_vide"
    assert check(gh, s, "z2", Order(Actuator.POMPE_NUTRI, "off")).ok  # off always allowed
    assert check(gh, s, "z1", Order(Actuator.POMPE_NUTRI, "on", duree_s=30)).ok  # z1: no tank
    feed(s, "z2", "niveau_cuve", 80, NOON - minutes(10))  # stale level = unknown
    assert check(gh, s, "z2", order).limite == "securite.cuve_inconnue"


def test_presence_temperature_ph_limits(gh):
    s = GreenhouseState()
    feed(s, "z1", "presence", 1, NOON)
    assert (
        check(gh, s, "z1", Order(Actuator.BRUMISATEUR, "on", duree_s=60)).limite
        == "securite.presence"
    )
    feed(s, "z1", "temperature", 36, NOON)
    assert check(gh, s, "z1", Order(Actuator.CHAUFFAGE, "on")).limite == "securite.t_max"
    feed(s, "z1", "temperature", 4, NOON)
    assert check(gh, s, "z1", Order(Actuator.VENTILO, "pwm", 100)).limite == "securite.t_min"
    feed(s, "z2", "niveau_cuve", 80, NOON)
    feed(s, "z2", "ph", 4.2, NOON)
    assert (
        check(gh, s, "z2", Order(Actuator.POMPE_PH_DOWN, "on", duree_s=2)).limite
        == "securite.ph_bas"
    )
    assert (
        check(gh, s, "z2", Order(Actuator.CHAUFFAGE, "on")).limite == "securite.actionneur_inconnu"
    )


def watch(gh, s, now=NOON):
    ctxs = {z.id: ctx(gh, s, z.id, now) for z in gh.cfg.zones}
    return {p.regle.id: p for p in safety.watch(s, ctxs)}


def test_watch_t_max_cuts_heating_and_alerts(gh):
    s = GreenhouseState()
    feed(s, "z1", "temperature", 36.5, NOON)
    set_actuator(s, "z1", "chauffage", "on", NOON)
    p = watch(gh, s)["securite.t_max"]
    assert p.niveau == 0 and p.type == "securite" and p.alerte.niveau == "critique"
    assert p.orders == [Order(Actuator.CHAUFFAGE, "off", texte="T° max")]


def test_watch_ph_tank_presence_muted_offline(gh):
    s = GreenhouseState()
    feed(s, "z2", "ph", 8.4, NOON, node="esp32-03")
    feed(s, "z2", "niveau_cuve", 3, NOON, node="esp32-03")
    set_actuator(s, "z2", "pompe_nutri", "on", NOON)
    feed(s, "z1", "presence", 2, NOON)
    set_actuator(s, "z1", "brumisateur", "on", NOON)
    feed(s, "z1", "humidite_sol", 50, NOON - minutes(6), node="esp32-02", emplacement="z1-A1")
    s.on_message("serre/esp32-02/status", b"offline")
    w = watch(gh, s)
    assert w["securite.ph"].alerte.niveau == "critique" and not w["securite.ph"].orders
    assert w["securite.cuve_vide"].orders == [Order(Actuator.POMPE_NUTRI, "off", texte="cuve vide")]
    assert w["securite.presence"].orders[0].actuator == Actuator.BRUMISATEUR
    assert "muet" in w["securite.capteur_muet"].alerte.message
    assert w["securite.noeud_offline"].zone == "z1"  # the zone the node publishes for


def test_watch_frozen_sensor(gh):
    s = GreenhouseState()
    for i in range(40):
        feed(s, "z1", "temperature", 21.7, NOON - minutes(40 - i))
    assert "securite.capteur_fige" in watch(gh, s)
    feed(s, "z1", "temperature", 21.8, NOON)
    assert "securite.capteur_fige" not in watch(gh, s)
