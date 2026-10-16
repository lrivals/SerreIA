""" "Classification → action" rules (docs/10 §5): confirmation, species check, one test per
row of the table. Synthetic VisionResults, no model."""

import yaml

from edge.controller.config import DEFAULT_CONFIG, Greenhouse, SerreCfg
from edge.controller.state import GreenhouseState
from edge.controller.vision_rules import VisionRules

from .controller_utils import (
    NOON,
    RIGHT,
    ctx,
    feed,
    feed_captures,
    feed_vision,
    greenhouse,
    minutes,
    set_actuator,
    vision,
)

LAST = NOON + minutes(20)  # time of the third capture


def greenhouse_with(espece_a1: str) -> Greenhouse:
    raw = yaml.safe_load(DEFAULT_CONFIG.read_text())
    emp = raw["zones"][0]["emplacements"][0]
    assert emp["id"] == "z1-A1"
    emp["plante"]["espece"] = espece_a1
    cfg = SerreCfg.model_validate(raw)
    return Greenhouse(cfg, cfg.load_recipes())


def evaluate(state, gh=None, now=LAST, zone="z1"):
    return VisionRules().evaluate(ctx(gh or greenhouse(), state, zone, now))


def air(state, hr, t, at=LAST):
    for sensor, v in (("humidite", hr), ("temperature", t)):
        feed(state, "z1", sensor, v, at - minutes(30))
        feed(state, "z1", sensor, v, at)


def ids(props):
    return sorted(p.regle.id for p in props)


def test_confirmation_needs_n_identical_confident_captures():
    state = GreenhouseState()
    air(state, 92, 20)
    feed_captures(state, "z1", "tomate/maladie/mildiou", NOON, n=2)
    assert evaluate(state, now=NOON + minutes(10)) == []  # 2 captures only
    feed_vision(state, "z1", vision(LAST, "tomate/maladie/mildiou", conf=0.4))
    assert evaluate(state) == []  # the third one is not confident enough
    feed_vision(state, "z1", vision(LAST + minutes(10), "tomate/maladie/septoriose"))
    assert evaluate(state, now=LAST + minutes(10)) == []  # mixed classes


def test_mildew_confirmed_in_humid_air():
    state = GreenhouseState()
    air(state, 92, 20)
    feed_captures(state, "z1", "tomate/maladie/mildiou", NOON)
    props = {p.regle.id: p for p in evaluate(state)}
    assert sorted(props) == ["maladie.mildiou.isolement", "maladie.mildiou.plante"]
    auto, prop = props["maladie.mildiou.plante"], props["maladie.mildiou.isolement"]
    assert not auto.validation and auto.plantes == [("z1-A1", "malade")]
    assert auto.consigne.nom == "humidite_max" and auto.consigne.delta == -10
    assert auto.consigne.duree_s == 72 * 3600
    assert auto.alerte.niveau == "warning" and auto.type == "exceptionnelle"
    assert prop.validation and prop.plantes == [("z1-A1", "isolee")]
    v = auto.preuves.vision[0]
    assert v.emplacement == "z1-A1" and v.confirmations == 3 and v.classe_conf == 0.85
    assert {c.agregat for c in auto.preuves.capteurs} >= {"duree_au_dessus", "moyenne_12h"}
    assert auto.preuves.consignes["humidite"]
    assert "3 images" in auto.explication and auto.emplacements == ["z1-A1"]


def test_disease_without_its_conditions_is_only_watched():
    state = GreenhouseState()
    air(state, 60, 20)  # dry air: no mildew conditions
    feed_captures(state, "z1", "tomate/maladie/mildiou", NOON)
    (p,) = evaluate(state)
    assert p.regle.id == "vision.anormal.surveillance" and not p.validation
    assert p.plantes == [("z1-A1", "a_surveiller")] and p.alerte.niveau == "info"


def test_species_mismatch_gives_an_alert_only():
    state = GreenhouseState()
    air(state, 92, 20)
    feed_captures(state, "z1", "poivron/maladie/tache_bacterienne", NOON)
    (p,) = evaluate(state)
    assert p.regle.id == "vision.espece.incoherence"
    assert not p.orders and not p.plantes and not p.captures
    assert "poivron" in p.explication and "tomate" in p.explication


def test_camera_seeing_only_species_outside_the_taxonomy_triggers_nothing():
    state = GreenhouseState()
    feed_captures(state, "z2", "laitue/virus/mosaique", NOON, camera="cam-z2-a", bbox=None)
    assert evaluate(state, zone="z2") == []


def test_powdery_mildew_watch_and_recapture():
    gh = greenhouse_with("courge")
    state = GreenhouseState()
    air(state, 55, 24)
    feed_captures(state, "z1", "courge/maladie/oidium", NOON)
    (p,) = evaluate(state, gh)
    assert p.regle.id == "maladie.oidium.surveillance" and not p.validation
    assert p.captures == ["cam-z1-a"] and p.plantes == [("z1-A1", "a_surveiller")]
    state.zone("z1").rule_fired[p.regle.id] = LAST  # captured: wait for the period
    (p,) = evaluate(state, gh, now=LAST + minutes(30))
    assert p.captures == []
    air(state, 85, 24, at=LAST + minutes(31))  # too humid for powdery mildew: only watched
    assert ids(evaluate(state, gh, now=LAST + minutes(31))) == ["vision.anormal.surveillance"]


def test_leaf_spots_with_misting_propose_to_stop_it():
    state = GreenhouseState()
    air(state, 70, 22)
    feed_captures(state, "z1", "tomate/maladie/septoriose", NOON)
    assert ids(evaluate(state)) == ["vision.anormal.surveillance"]  # no misting used
    set_actuator(state, "z1", "brumisateur", "on", LAST)
    (p,) = evaluate(state)
    assert p.regle.id == "maladie.taches.arrosage" and p.validation
    assert [(o.actuator, o.action) for o in p.orders] == [("brumisateur", "off")]
    assert "inspection" in p.explication


def test_pest_in_dry_air_proposes_light_misting():
    state = GreenhouseState()
    air(state, 45, 24)
    feed_captures(state, "z1", "tomate/nuisible/tetranyque", NOON)
    (p,) = evaluate(state)
    assert p.regle.id == "nuisible.brumisation" and p.validation
    assert [(o.actuator, o.action, o.duree_s) for o in p.orders] == [("brumisateur", "on", 30)]
    assert p.captures == ["cam-z1-a"]
    air(state, 65, 24, at=LAST + minutes(1))
    (p,) = evaluate(state, now=LAST + minutes(1))
    assert p.orders == [] and p.captures == ["cam-z1-a"]  # humid enough: inspection only


def test_virus_proposes_isolation_with_a_critical_alert():
    state = GreenhouseState()
    feed_captures(state, "z1", "tomate/virus/mosaique", NOON)
    (p,) = evaluate(state)
    assert p.regle.id == "virus.isolement" and p.validation
    assert p.plantes == [("z1-A1", "isolee")] and p.alerte.niveau == "critique"


def test_healthy_but_anomalous_plant_is_captured_again():
    state = GreenhouseState()
    feed_captures(state, "z1", "basilic/sain/sain", NOON, bbox=RIGHT, anomalie=0.2)
    assert evaluate(state) == []
    feed_vision(state, "z1", vision(LAST + minutes(10), "basilic/sain/sain", bbox=RIGHT,
                                    anomalie=0.9))  # fmt: skip
    (p,) = evaluate(state, now=LAST + minutes(10))
    assert p.regle.id == "vision.anomalie.recapture" and not p.validation
    assert p.captures == ["cam-z1-a"] and p.orders == [] and p.emplacements == ["z1-A2"]
    assert p.alerte.niveau == "info"


def test_green_surface_drop_proposes_watering():
    state = GreenhouseState()
    start = NOON - minutes(30 * 60)
    for i in range(3):
        feed_vision(state, "z1", vision(start + minutes(10 * i), "tomate/sain/sain", px=50_000))
    for i in range(3):
        feed_vision(state, "z1", vision(LAST - minutes(10 * i), "tomate/sain/sain", px=45_000))
    assert evaluate(state) == []  # −10 %: under the threshold
    feed_vision(state, "z1", vision(LAST + minutes(10), "tomate/sain/sain", px=20_000))
    (p,) = evaluate(state, now=LAST + minutes(10))
    assert p.regle.id == "croissance.surface.arrosage" and p.validation
    assert [(o.actuator, o.duree_s) for o in p.orders] == [("pompe_nutri", 45)]
    assert p.emplacements == ["z1-A1", "z1-A2"]
    assert p.preuves.capteurs[0].topic == "serre/z1/vision/cam-z1-a"


def test_validation_is_configurable_per_rule():
    raw = yaml.safe_load(DEFAULT_CONFIG.read_text())
    raw["regles"] = {"validation": {"virus.isolement": False}, "confirmations": 2}
    cfg = SerreCfg.model_validate(raw)
    gh = Greenhouse(cfg, cfg.load_recipes())
    state = GreenhouseState()
    feed_captures(state, "z1", "tomate/virus/mosaique", NOON, n=2)
    (p,) = evaluate(state, gh, now=NOON + minutes(10))
    assert p.regle.id == "virus.isolement" and not p.validation
