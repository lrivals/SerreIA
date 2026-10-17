"""Builder of the greenhouse (docs/12 §2.1): structure, plants, configuration published."""

import pytest
import yaml

from .api_utils import make_api


@pytest.fixture
def api(tmp_path):
    return make_api(tmp_path)


def test_zone_emplacement_crud(api):
    c = api.client
    z = c.post("/api/zones", json={"nom": "Semis"}).json()
    assert z["id"] == "z3" and z["serre_id"]  # next free id, the only serre
    e = c.post(
        "/api/emplacements",
        json={
            "zone_id": "z3",
            "code": "b2",
            "mode_culture": "substrat",
            "contenant": {"type": "godet", "volume_l": 0.5},
        },
    )
    assert e.status_code == 201
    e = e.json()
    assert (e["id"], e["rangee"], e["colonne"]) == ("z3-B2", 2, 2) and e["contenant_id"]
    assert (
        c.post(
            "/api/emplacements", json={"zone_id": "z3", "code": "B2", "mode_culture": "terre"}
        ).status_code
        == 409
    )
    assert (
        c.post(
            "/api/emplacements", json={"zone_id": "z3", "code": "C1", "mode_culture": "sable"}
        ).status_code
        == 422
    )
    r = c.patch("/api/emplacements/z3-B2", json={"mode_culture": "hydro_dwc"}).json()
    assert r["mode_culture"] == "hydro_dwc" and r["contenant_id"] == e["contenant_id"]
    assert c.delete("/api/zones/z3").status_code == 409  # still has an emplacement
    assert c.delete("/api/emplacements/z3-B2").status_code == 204
    assert c.delete("/api/zones/z3").status_code == 204
    assert c.get("/api/zones/z3").status_code == 404
    assert [z["id"] for z in c.get("/api/zones").json()] == ["z1", "z2"]


def test_plan_of_a_zone(api):
    plan = api.client.get("/api/zones/z1/plan").json()
    by_id = {e["id"]: e for e in plan["emplacements"]}
    a1 = by_id["z1-A1"]
    assert a1["plante"]["id"] == "tomate-1" and a1["contenant"]["volume_l"] == 11
    assert "sht41-z1" in a1["capteurs"] and "sol-z1-A1" in a1["capteurs"]
    assert "sol-z1-A1" not in by_id["z1-A2"]["capteurs"]
    assert plan["cameras"][0]["id"] == "cam-z1-a"


def test_plants_create_move_history(api):
    c = api.client
    c.post("/api/emplacements", json={"zone_id": "z1", "code": "B1", "mode_culture": "terre"})
    p = c.post(
        "/api/plantes",
        json={
            "espece": "tomate",
            "stade": "semis",
            "recette_id": "tomate-standard",
            "emplacement": "z1-B1",
        },
    ).json()
    assert p["id"] == "tomate-2" and p["emplacement"] == "z1-B1"
    bad = {"espece": "tomate", "stade": "hiver", "recette_id": "tomate-standard"}
    assert c.post("/api/plantes", json=bad).status_code == 422
    # Occupied emplacement: refused, nothing moved.
    r = c.post("/api/plantes/tomate-2/deplacer", json={"emplacement": "z1-A1"})
    assert r.status_code == 409 and "tomate-1" in r.json()["detail"]
    api.at(api.clock["t"].replace(hour=11))
    assert (
        c.post("/api/plantes/tomate-1/deplacer", json={"emplacement": None}).json()["emplacement"]
        is None
    )
    assert (
        c.post("/api/plantes/tomate-2/deplacer", json={"emplacement": "z1-A1"}).json()[
            "emplacement"
        ]
        == "z1-A1"
    )
    h = c.get("/api/plantes/tomate-2/historique").json()
    assert [a["emplacement"] for a in h["affectations"]] == ["z1-B1", "z1-A1"]
    assert h["affectations"][0]["fin"] is not None and h["affectations"][1]["fin"] is None
    assert [p["id"] for p in c.get("/api/plantes", params={"zone": "z1"}).json()] == [
        "basilic-1",
        "tomate-2",
    ]
    r = c.patch("/api/plantes/tomate-2", json={"stade": "croissance", "etat_sante": "a_surveiller"})
    assert r.json()["etat_sante"] == "a_surveiller"
    assert c.patch("/api/plantes/tomate-2", json={"etat_sante": "mort"}).status_code == 422
    # The emplacement keeps the history of its plants.
    assert c.delete("/api/emplacements/z1-B1").status_code == 409


def test_recipes_are_validated(api):
    c = api.client
    stades = {
        "croissance": {
            "temperature": {"jour": [18, 24], "nuit": [14, 16]},
            "humidite": [60, 80],
            "photoperiode_h": 14,
        }
    }
    assert (
        c.post(
            "/api/recettes", json={"id": "fraise", "espece": "fraisier", "stades": stades}
        ).status_code
        == 201
    )
    bad = {"croissance": dict(stades["croissance"], humidite=[80, 60])}
    assert c.patch("/api/recettes/fraise", json={"stades": bad}).status_code == 422
    assert c.delete("/api/recettes/tomate-standard").status_code == 409  # used by tomate-1


def test_coherence_diff_and_publication(api, tmp_path):
    c = api.client
    coh = c.get("/api/config/coherence").json()
    assert coh["valide"] and any("basilic" in w for w in coh["avertissements"])
    first = c.post("/api/config/publier").json()
    assert first["nouvelle"] and (tmp_path / "serre.yaml").is_file()
    v = first["config_version"]
    assert yaml.safe_load((tmp_path / "serre.yaml").read_text())["config_version"] == v
    assert c.get("/api/config/diff").json()["identique"]
    assert c.post("/api/config/publier").json() == dict(first, nouvelle=False)

    # An hydro emplacement in a zone without pH / EC sensor: a warning, then a diff.
    c.post("/api/emplacements", json={"zone_id": "z1", "code": "C1", "mode_culture": "hydro_dwc"})
    assert any(
        "z1-C1" in w and "ph" in w for w in c.get("/api/config/coherence").json()["avertissements"]
    )
    d = c.get("/api/config/diff").json()
    assert not d["identique"] and "+  - id: z1-C1" in d["diff"] and d["de"] == f"v{v}"
    assert c.post("/api/config/publier").json()["config_version"] == v + 1
    assert [x["version"] for x in c.get("/api/config/versions").json()] == [v + 1, v]
    assert "z1-C1" in c.get("/api/config/diff", params={"de": v, "a": v + 1}).json()["diff"]

    # An unknown stage: invalid configuration, nothing published.
    c.post(
        "/api/recettes",
        json={
            "id": "r",
            "espece": "x",
            "stades": {
                "a": {
                    "temperature": {"jour": [1, 2], "nuit": [1, 2]},
                    "humidite": [1, 2],
                    "photoperiode_h": 1,
                }
            },
        },
    )
    c.post(
        "/api/plantes",
        json={"espece": "x", "stade": "a", "recette_id": "r", "emplacement": "z1-C1"},
    )
    c.patch(
        "/api/recettes/r",
        json={
            "stades": {
                "b": {
                    "temperature": {"jour": [1, 2], "nuit": [1, 2]},
                    "humidite": [1, 2],
                    "photoperiode_h": 1,
                }
            }
        },
    )
    assert not c.get("/api/config/coherence").json()["valide"]
    assert c.post("/api/config/publier").status_code == 422


def test_disposition_of_the_game_view(api, tmp_path):
    """Placement in the game view (docs/13 §3): stored and returned, never exported."""
    c = api.client
    d = {"x": 3, "y": 4, "orientation": "sud", "sprite": "terracotta_pot"}
    z = c.post(
        "/api/zones",
        json={"nom": "Jeu", "disposition": {"x": 20, "y": 0, "largeur": 8, "hauteur": 5}},
    )
    assert z.json()["disposition"] == {"x": 20, "y": 0, "largeur": 8, "hauteur": 5}
    e = c.post(
        "/api/emplacements",
        json={"zone_id": z.json()["id"], "code": "A1", "mode_culture": "terre", "disposition": d},
    ).json()
    assert e["disposition"] == d
    r = c.patch(f"/api/emplacements/{e['id']}", json={"disposition": {"x": 5, "y": 4}}).json()
    assert r["disposition"] == {"x": 5, "y": 4}
    assert c.patch(f"/api/emplacements/{e['id']}", json={"mode_culture": "substrat"}).json()[
        "disposition"
    ]
    plan = c.get(f"/api/zones/{z.json()['id']}/plan").json()
    assert plan["zone"]["disposition"]["largeur"] == 8
    assert plan["emplacements"][0]["disposition"] == {"x": 5, "y": 4}

    a = c.get("/api/actionneurs").json()[0]
    r = c.patch(f"/api/actionneurs/{a['id']}", json={"disposition": {"x": 1, "y": 0}}).json()
    assert r["disposition"] == {"x": 1, "y": 0} and r["type"] == a["type"]
    cap = c.get("/api/capteurs").json()[0]
    from urllib.parse import quote

    r = c.patch(f"/api/capteurs/{quote(cap['id'])}", json={"disposition": {"x": 2, "y": 6}}).json()
    assert r["disposition"] == {"x": 2, "y": 6}
    cam = c.get("/api/cameras").json()[0]
    r = c.patch(
        f"/api/cameras/{cam['id']}", json={"disposition": {"x": 0, "y": 0, "orientation": "est"}}
    )
    assert r.json()["disposition"]["orientation"] == "est" and r.json()["zone_id"] == cam["zone_id"]
    assert r.json()["regions"] == cam["regions"]  # same zone: regions kept
    cuve = c.post("/api/cuves", json={"id": "cuve-jeu", "disposition": {"x": 9, "y": 9}}).json()
    assert cuve["disposition"] == {"x": 9, "y": 9}
    assert c.patch("/api/cuves/cuve-jeu", json={"disposition": None}).json()["disposition"] is None

    bad = {"x": -1, "y": 0}, {"x": 0, "y": 0, "orientation": "haut"}, {"x": 0}
    for b in bad:
        assert c.patch(f"/api/emplacements/{e['id']}", json={"disposition": b}).status_code == 422

    c.post("/api/config/publier")
    assert "disposition" not in (tmp_path / "serre.yaml").read_text()
