"""Recipes, zone setpoints and greenhouse configuration (docs/09 §6, §8)."""

import shutil
from datetime import date

import pytest
import yaml

from edge.controller.config import ConfigWatcher, Greenhouse, SerreCfg, load_greenhouse
from edge.controller.recipes import (
    PlantStage,
    Recipe,
    StageSetpoints,
    intersect,
    load_recipes,
    zone_setpoints,
)


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
    assert z2.ec == (0.9, 1.5)  # lettuce, finishing stage (docs/22 L1)
    assert z1.vpd == (0.5, 1.2) and z1.ec_drainage == (2.2, 3.8)  # tomato in flower
    assert recipes["fraise-substrat"].stage("production").ec == (1.0, 1.5)  # docs/22 L2
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


def test_model_validation_of_sensors_and_cameras():
    def fails(edit, match):
        raw = yaml.safe_load(open("edge/controller/serre.yaml"))
        edit(raw)
        with pytest.raises(ValueError, match=match):
            SerreCfg.model_validate(raw)

    fails(lambda r: r["cameras"][0]["emplacements_visibles"].append("z2-A1"), "hors de la zone")
    fails(lambda r: r["cameras"][1].update(regions={"z1-A1": [0, 0, 1, 1]}), "non visibles")
    fails(lambda r: r["cameras"][0]["regions"].update({"z1-A1": [0, 0, 1.5, 1]}), r"\[0, 1\]")
    fails(lambda r: r["zones"][1].update(cuve="cuve-inconnue"), "cuve inconnue")
    fails(lambda r: r["capteurs"].append({**r["capteurs"][0], "id": "bis"}), "même canal")
    fails(lambda r: r["capteurs"][0].update(cuve=True), "pas de cuve")


def test_consistency_warnings():
    from edge.controller.coherence import check

    raw = yaml.safe_load(open("edge/controller/serre.yaml"))
    cfg = SerreCfg.model_validate(raw)
    assert check(cfg, {"tomate", "basilic", "laitue"}) == []  # the sample is consistent
    raw["capteurs"] = [c for c in raw["capteurs"] if c["id"] != "ph-cuve-z2"]
    raw["actionneurs"].append(
        {"id": "ph-z1", "zone": "z1", "type": "pompe_ph_down", "duree_max_s": 10}
    )
    raw["cameras"][0]["regions"].pop("z1-A2")
    warnings = check(SerreCfg.model_validate(raw), {"tomate"})
    assert any("z2-A1" in w and "ph" in w and "cuve-z2" in w for w in warnings)
    assert any(w.startswith("ph-z1 : pompe doseuse") for w in warnings)
    assert any(w.startswith("cam-z1-a") and "z1-A2" in w for w in warnings)
    assert sum("hors taxonomie" in w for w in warnings) == 2  # basilic, laitue


def test_inline_recipes_and_vision_auto():
    raw = yaml.safe_load(open("edge/controller/serre.yaml"))
    raw["recettes"] = yaml.safe_load(open("edge/controller/recettes.yaml"))
    cfg = SerreCfg.model_validate(raw)
    gh = Greenhouse(cfg, cfg.load_recipes(), especes={"tomate"})
    assert gh.setpoints["z1"] == load_greenhouse().setpoints["z1"]
    assert gh.vision_auto("cam-z1-a")  # sees a tomato
    assert not gh.vision_auto("cam-z2-a")  # only a lettuce, out of taxonomy
    assert gh.vision_auto("cam-inconnue")  # undeclared: default behaviour


# --- docs/22: fields from the literature ----------------------------------------------------


def stage(**kw):
    return StageSetpoints.model_validate(
        {"temperature": {"jour": [20, 25], "nuit": [15, 18]}, "humidite": [50, 70],
         "photoperiode_h": 16, **kw}
    )  # fmt: skip


def test_ec_apport_is_an_alias_of_ec():
    assert stage(ec_apport=[2.0, 2.5]).ec == (2.0, 2.5)
    assert stage(ec=[2.0, 2.5]).ec == (2.0, 2.5)
    with pytest.raises(ValueError, match="min > max"):
        stage(vpd=[1.2, 0.5])


def test_lettuce_stage_from_its_age():
    lettuce = load_recipes("edge/controller/recettes.yaml")["laitue-hydro"]
    assert [lettuce.stage_for_age(d) for d in (5, 25, 35, 400)] == [
        "pepiniere",
        "croissance",
        "finition",
        "finition",
    ]
    assert lettuce.stage("pepiniere").ec[1] <= 0.5  # no 1.0 mS/cm on young lettuce
    assert load_recipes("edge/controller/recettes.yaml")["tomate-standard"].stage_for_age(5) is None


def auto_lettuce(semis):
    raw = yaml.safe_load(open("edge/controller/serre.yaml"))
    raw["zones"][1]["emplacements"][0]["plante"].update(stade="auto", date_semis=semis)
    return SerreCfg.model_validate(raw)


def test_auto_stage_in_the_greenhouse():
    cfg = auto_lettuce("2026-07-01")
    gh = Greenhouse(cfg, cfg.load_recipes(), today=date(2026, 7, 6))
    assert gh.stades["laitue-1"] == "pepiniere" and gh.setpoints["z2"].ec == (0.25, 0.5)
    assert not gh.setpoints["z2"].complement_led
    gh = Greenhouse(cfg, cfg.load_recipes(), today=date(2026, 8, 5))
    assert gh.stades["laitue-1"] == "finition" and gh.auto_stages
    assert gh.stades["tomate-1"] == "floraison"  # manual stage kept
    raw = yaml.safe_load(open("edge/controller/serre.yaml"))
    raw["zones"][1]["emplacements"][0]["plante"]["stade"] = "auto"  # no date_semis
    cfg = SerreCfg.model_validate(raw)
    with pytest.raises(ValueError, match="date_semis"):
        Greenhouse(cfg, cfg.load_recipes())


def test_zone_merge_of_the_new_fields():
    recipes = {
        "a": Recipe(espece="a", stades={"s": stage(dli_max=15, vpd=[0.4, 1.0])}),
        "b": Recipe(espece="b", stades={"s": stage(dli_max=13, complement_led=False)}),
    }
    sp = zone_setpoints([PlantStage("a", "s"), PlantStage("b", "s")], recipes)
    assert sp.dli_max == 13 and not sp.complement_led and sp.vpd == (0.4, 1.0)
    assert not sp.brumisation_nuit
    assert sp.as_evidence()["dli_max"] == 13
