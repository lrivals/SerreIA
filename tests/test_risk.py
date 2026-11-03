"""Disease risk index and mildew rule (docs/06 §4, docs/10 §5)."""

from datetime import timedelta

import pytest

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


# --- docs/22 L5: infection, incubation; L7: Botrytis --------------------------------------


def greenhouse_with(espece_a1: str):
    import yaml

    from edge.controller.config import DEFAULT_CONFIG, Greenhouse, SerreCfg

    raw = yaml.safe_load(DEFAULT_CONFIG.read_text())
    raw["zones"][0]["emplacements"][0]["plante"]["espece"] = espece_a1
    raw["zones"][0]["emplacements"][1]["plante"]["espece"] = espece_a1
    cfg = SerreCfg.model_validate(raw)
    return Greenhouse(cfg, cfg.load_recipes())


def air(s, ts, hr, t):
    feed(s, "z1", "humidite", hr, ts)
    feed(s, "z1", "temperature", t, ts)


def test_cucumber_incubation_reaches_symptoms_in_67_h_at_20_c():
    gh, s = greenhouse_with("concombre"), GreenhouseState()
    start = NIGHT - timedelta(hours=1)
    t, infected_at, symptoms_at, alerts = start, None, None, []
    for _ in range(int(75 * 6)):
        wet = t - start < timedelta(hours=4)  # 4 h of leaf wetness, then dry air
        air(s, t, 95.0 if wet else 70.0, 20.0)
        props = risk.mildew(ctx(gh, s, "z1", t))
        alerts += [p.alerte.key for p in props if p.alerte]
        rec = s.zone("z1").infections.get("mildiou/concombre")
        if rec is not None and infected_at is None:
            infected_at = t
        if rec is not None and rec.progression >= 1 and symptoms_at is None:
            symptoms_at = t
        t += minutes(10)
    assert infected_at - start == timedelta(hours=2)  # LWD ≥ 2 h and 2 h × 20 °C ≥ 40 h·°C
    hours = (symptoms_at - infected_at).total_seconds() / 3600
    assert abs(hours - 1 / 0.015) <= 1  # 67 h (`2022-liu#004.0`)
    assert "z1/maladie.mildiou.ventilation" in alerts  # during the wetness
    assert "z1/maladie.mildiou.incubation" in alerts  # dry air, incubation running


def test_cucumber_short_wetness_or_cold_does_not_infect():
    gh = greenhouse_with("concombre")
    s = GreenhouseState()
    humid_night(s, 1.5, hr=95, t=20)  # under 2 h
    assert not risk.mildew_risk(ctx(gh, s, "z1", NIGHT)).conditions
    s = GreenhouseState()
    humid_night(s, 3, hr=95, t=4)  # T° during the wetness out of 5–30 °C
    assert not risk.mildew_risk(ctx(gh, s, "z1", NIGHT)).conditions


def test_tomato_keeps_the_unsourced_10_h_without_incubation():
    gh, s = greenhouse(), GreenhouseState()
    humid_night(s, 11)
    c = ctx(gh, s, "z1", NIGHT)
    (p,) = risk.mildew(c)
    assert p.regle.version == 2 and "seuils non sourcés" in p.explication
    rec = s.zone("z1").infections["mildiou/tomate"]
    assert rec.progression == 0  # no sourced incubation rate for tomato
    idx = risk.mildew_risk(c)
    assert {e.etat for e in idx.especes} == {"infection"}
    assert {e.agregat for e in p.preuves.capteurs} >= {"moyenne_humectation", "degres_heures"}


def test_temperature_is_taken_during_the_wetness():
    gh, s = greenhouse(), GreenhouseState()
    hot = NIGHT - timedelta(hours=14)
    for i in range(18):  # 3 h of hot dry air, then 11 h of humid night at 24 °C
        air(s, hot + minutes(10 * i), 50.0, 40.0)
    humid_night(s, 11, t=24.0)
    idx = risk.mildew_risk(ctx(gh, s, "z1", NIGHT))
    assert idx.t_moyenne > 25  # the old 12 h mean would have refused
    assert idx.t_humectation == pytest.approx(24.0) and idx.conditions


def test_botrytis_alert_at_night_and_heat_vent_cycle_before_the_day():
    gh, s = greenhouse(), GreenhouseState()
    humid_night(s, 3, hr=93, t=17)
    (p,) = risk.botrytis(ctx(gh, s, "z1", NIGHT))  # 03:00 local, 3 h before the day
    assert p.regle.id == risk.BOTRYTIS_ID and p.orders == [] and p.alerte.niveau == "warning"
    assert {e.agregat for e in p.preuves.capteurs} >= {"vpd", "ecart_point_de_rosee"}
    late = NIGHT + timedelta(hours=2)  # 05:00 local
    for i in range(13):
        air(s, NIGHT + minutes(10 * i), 93, 17)
    (p,) = risk.botrytis(ctx(gh, s, "z1", late))
    assert {(o.actuator, o.duree_s) for o in p.orders} == {("chauffage", 900), ("ventilo", 900)}
    s.zone("z1").rule_fired[risk.BOTRYTIS_ID] = late
    (p,) = risk.botrytis(ctx(gh, s, "z1", late + minutes(10)))
    assert p.orders == []  # once per period
    warm = GreenhouseState()
    humid_night(warm, 3, hr=93, t=25)
    assert risk.botrytis(ctx(gh, warm, "z1", NIGHT)) == []
    day = NIGHT + timedelta(hours=7)  # 10:00 local, same humid air
    for i in range(7):
        air(s, day - minutes(10 * i), 93, 17)
    assert risk.botrytis_risk(ctx(gh, s, "z1", day)).hr == pytest.approx(93)
    assert risk.botrytis(ctx(gh, s, "z1", day)) == []  # by day
