"""Printed parts (docs/20): dimensions, rules, labels and, with FreeCAD, the build."""

import json
import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from hardware import PIECES
from hardware import params as hp

HARDWARE = Path(hp.__file__).parent
PIECES_DIR = HARDWARE / "pieces"


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


def test_one_label_per_emplacement():
    from tools.hardware.etiquettes import etiquettes

    labels = etiquettes()
    assert [lab["id"] for lab in labels] == ["z1-A1", "z1-A2", "z2-A1"]
    assert labels[0]["plante"] == "tomate-1" and labels[2]["zone"] == "z2"


def test_label_qr_code():
    pytest.importorskip("segno")
    from tools.hardware.etiquettes import qr_matrice

    m = qr_matrice("z1-A1")
    assert len(m) >= 21 and all(len(ligne) == len(m) for ligne in m)
    assert {v for ligne in m for v in ligne} == {0, 1}


def test_labels_file(tmp_path):
    from tools.hardware.etiquettes import main

    out = tmp_path / "etiquettes.json"
    main(["--out", str(out), "--url", "https://serre.local/e/"])
    assert len(json.loads(out.read_text())) == 3


def test_every_part_is_built_and_documented():
    modules = {f.stem for f in PIECES_DIR.glob("*.py")} - {"__init__"}
    assert modules == set(PIECES)
    readme = (HARDWARE / "README.md").read_text()
    assert all(f"pieces/{m}.py" in readme for m in PIECES)


FREECAD = shutil.which("freecadcmd") or shutil.which("freecad.cmd")  # apt or snap


@pytest.mark.skipif(not FREECAD, reason="FreeCAD not installed")
def test_freecad_build():
    # under the repository, not tmp_path: the FreeCAD snap has its own /tmp
    out = HARDWARE / "build" / "_test"
    shutil.rmtree(out, ignore_errors=True)
    env = {**os.environ, "SERREIA_HW_OUT": str(out)}
    r = subprocess.run(
        [FREECAD, str(HARDWARE / "build.py")],
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    for m in PIECES:
        stl = list((out / m).glob("*.stl"))
        assert stl and all(f.stat().st_size > 0 for f in stl), m


def test_rack_and_bulkhead_rules():
    assert any("cran_pas" in e for e in hp.verifier(replace(hp.Params(), cran_pas=10.0)))
    assert any("passe_trou_d" in e for e in hp.verifier(replace(hp.Params(), passe_trou_d=9.0)))
