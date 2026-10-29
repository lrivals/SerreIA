"""Printed parts (docs/20): dimensions, rules, labels and, with FreeCAD, the build."""

from dataclasses import replace

import pytest

from hardware import params as hp


def test_nominal_dimensions_follow_the_rules():
    assert hp.verifier(hp.Params()) == []


@pytest.mark.parametrize(
    "change, mot",
    [
        ({"jeu": 0.05}, "jeu"),
        ({"tube_d": 25.0}, "emmanchement"),
        ({"cuve_niveau_max": 300.0}, "JSN-SR04T"),
        ({"ecart_ph_ec": 30.0}, "pH and EC"),
        ({"clip_enveloppe_deg": 180.0}, "wrap"),
        ({"arete_r": 0.5}, "edge radius"),
        ({"platine_l": 300.0}, "printer volume"),
        ({"abri_d_int": 116.0}, "abri_d_int"),
    ],
)
def test_each_rule_is_detected(change, mot):
    err = hp.verifier(replace(hp.Params(), **change))
    assert any(mot in e for e in err), err


def test_jsn_riser_fixes_the_blind_zone():
    p = replace(hp.Params(), cuve_niveau_max=300.0)
    assert hp.verifier(replace(p, jsn_rehausse=150.0)) == []


def test_measured_dimensions_override_the_nominal_ones(tmp_path):
    f = tmp_path / "mesures.toml"
    f.write_text("tube_d = 20.6\njeu = 0.25\n")
    p = hp.load(f)
    assert (p.tube_d, p.jeu, p.film_ep) == (20.6, 0.25, hp.Params().film_ep)
    assert "tube_d" not in hp.non_mesurees(f) and "jsn_d" in hp.non_mesurees(f)


def test_unknown_measure_is_rejected(tmp_path):
    f = tmp_path / "mesures.toml"
    f.write_text("tube_diametre = 20.6\n")
    with pytest.raises(ValueError, match="tube_diametre"):
        hp.load(f)


def test_repository_measures_load():
    assert hp.verifier(hp.load()) == []
    assert set(hp.A_MESURER) <= {f for f in vars(hp.Params())}
