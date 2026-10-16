"""Recipes, zone setpoints and greenhouse configuration (docs/09 §6, §8)."""

import shutil

import pytest
import yaml

from edge.controller.config import ConfigWatcher, SerreCfg, load_greenhouse
from edge.controller.recipes import PlantStage, Recipe, intersect, load_recipes, zone_setpoints


def recipe(t_jour, hr, ph=None):
    return Recipe.model_validate(
        {
            "espece": "x",
            "stades": {
                "s": {
                    "temperature": {"jour": t_jour, "nuit": [10, 15]},
                    "humidite": hr,
                    "photoperiode_h": 12,
                    **({"ph": ph} if ph else {}),
                }
            },
        }
    )


def test_intersect():
    assert intersect((20, 26), (22, 30)) == (22, 26)
    assert intersect((20, 22), (23, 30)) is None
    assert intersect(None, (1, 2)) == (1, 2)


def test_zone_setpoints_intersection_and_priority():
    recipes = {
        "a": recipe([20, 26], [60, 75], [5.8, 6.3]),
        "b": recipe([22, 30], [50, 65], [6.5, 7]),
    }
    sp = zone_setpoints([PlantStage("a", "s"), PlantStage("b", "s", prioritaire=True)], recipes)
    assert sp.temperature_jour == (22, 26) and sp.humidite == (60, 65)
    assert sp.ph == (6.5, 7) and sp.incompatibles == ["ph"]  # empty: the priority plant wins
    assert zone_setpoints([], recipes) is None
    soil = zone_setpoints([PlantStage("a", "s")], recipes, hydro=False)
    assert soil.ph is None


def test_sample_files_load():
    recipes = load_recipes("edge/controller/recettes.yaml")
    assert recipes["tomate-standard"].stage("floraison").humidite == (55, 70)
    gh = load_greenhouse()
    z1, z2 = gh.setpoints["z1"], gh.setpoints["z2"]
    assert z1.ph is None and z1.humidite_sol == (45, 65)  # soil zone: no pH / EC
    assert z2.ec == (1.0, 1.6)
    assert gh.cfg.zone("z2").hydro and gh.cfg.zone("z2").cuve
    assert gh.emplacement_setpoints("z1", "z1-A2").humidite_sol == (40, 65)  # basil


def test_config_validation():
    raw = yaml.safe_load(open("edge/controller/serre.yaml"))
    raw["actionneurs"].append({"id": "p", "zone": "z1", "type": "pompe_ph_down"})  # no duree_max_s
    with pytest.raises(ValueError, match="duree_max_s"):
        SerreCfg.model_validate(raw)
    raw["actionneurs"][-1] = {"id": "v2", "zone": "z1", "type": "ventilo"}  # second fan in z1
    with pytest.raises(ValueError, match="un seul"):
        SerreCfg.model_validate(raw)


def test_hot_reload_keeps_previous_on_error(tmp_path):
    shutil.copy("edge/controller/recettes.yaml", tmp_path / "recettes.yaml")
    raw = yaml.safe_load(open("edge/controller/serre.yaml"))
    raw["recettes"] = str(tmp_path / "recettes.yaml")
    path = tmp_path / "serre.yaml"
    path.write_text(yaml.safe_dump(raw))
    w = ConfigWatcher(path)
    assert w.get().version == 1
    raw["config_version"] = 2
    path.write_text(yaml.safe_dump(raw))
    w.mtime = 0  # force (same second mtime)
    assert w.get().version == 2
    path.write_text("zones: []")
    w.mtime = 0
    assert w.get().version == 2  # invalid file: previous configuration kept
