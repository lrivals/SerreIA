"""Disease risk index and mildew rule (docs/06 §4, docs/10 §5)."""

from datetime import timedelta

from common.mqtt import VisionResult
from edge.controller import risk
from edge.controller.state import GreenhouseState

from .controller_utils import NIGHT, ctx, feed, greenhouse, minutes


def humid_night(s, hours, hr=93.0, t=17.0):
    start = NIGHT - timedelta(hours=hours)
    for i in range(int(hours * 6) + 1):
        ts = start + minutes(10 * i)
        feed(s, "z1", "humidite", hr, ts)
        feed(s, "z1", "temperature", t, ts)


def vision(i, classe="tomate/maladie/mildiou", conf=0.9):
    return VisionResult(
        ts=NIGHT - minutes(30 - 10 * i),
        camera="cam-z1-a",
        image_id=f"img-{i}",
        modele="m",
        detections=[
            {
                "bbox": None,
                "espece": "tomate",
                "espece_conf": 0.9,
                "sante": "anormal",
                "sante_conf": conf,
                "classe": classe,
                "classe_conf": 0.8,
            }
        ],
        score_anomalie=0.1,
        surface_verte_px=10,
    )


def test_mildew_conditions_trigger_ventilation_once_per_period():
    gh, s = greenhouse(), GreenhouseState()
    humid_night(s, 11)
    c = ctx(gh, s, "z1", NIGHT)
    idx = risk.mildew_risk(c)
    assert idx.conditions and idx.humectation_h >= 10 and idx.score == 1.0
    p = risk.mildew(c)[0]
    assert p.type == "exceptionnelle" and p.orders[0].duree_s == 900
    assert {e.agregat for e in p.preuves.capteurs} >= {"duree_au_dessus", "moyenne_12h"}
    s.zone("z1").rule_fired[risk.RULE_ID] = NIGHT
    later = risk.mildew(ctx(gh, s, "z1", NIGHT + minutes(30)))[0]
    assert later.orders == [] and later.alerte is not None  # still risky, no new ventilation


def test_no_risk_when_too_cold_or_too_short():
    gh = greenhouse()
    s = GreenhouseState()
    humid_night(s, 11, t=6.0)
    assert not risk.mildew_risk(ctx(gh, s, "z1", NIGHT)).conditions
    s = GreenhouseState()
    humid_night(s, 5)
    assert risk.mildew(ctx(gh, s, "z1", NIGHT)) == []


def test_vision_confirmation_adds_evidence():
    gh, s = greenhouse(), GreenhouseState()
    humid_night(s, 2, hr=88)
    z = s.zone("z1")
    for i in range(3):
        z.on_vision(vision(i))
    assert len(risk.confirmed(z, "mildiou")) == 3
    p = risk.mildew(ctx(gh, s, "z1", NIGHT))[0]
    assert p.preuves.vision[0].classe == "tomate/maladie/mildiou"
    assert p.preuves.vision[0].confirmations == 3
    z.on_vision(vision(3, classe="tomate/maladie/septoriose"))
    assert risk.confirmed(z, "mildiou") == []  # the streak is broken


def test_cameras_seeing_only_out_of_taxonomy_species_are_ignored():
    s = GreenhouseState()
    for i in range(3):
        s.zone("z1").vision.append(vision(i))
    assert len(risk.confirmed(s.zone("z1"), "mildiou")) == 3
    assert risk.confirmed(s.zone("z1"), "mildiou", allowed=lambda cam: False) == []
    gh = greenhouse()
    gh.especes = frozenset()  # the tomato of cam-z1-a is now out of taxonomy too
    assert risk.mildew_risk(ctx(gh, s, "z1", NIGHT)).vision == []
