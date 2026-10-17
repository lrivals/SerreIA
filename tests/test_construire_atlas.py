"""Pixel-art atlas of the game view (tools/construire_atlas.py), on synthetic sprites."""

import json

import numpy as np
from PIL import Image

from tools import construire_atlas as ca


def rgba(h, w, color=(0, 128, 0), alpha=255):
    img = np.zeros((h, w, 4), np.uint8)
    img[..., :3] = color
    img[..., 3] = alpha
    return img


def test_nettoyer_drops_halo_and_white_haze_keeps_body():
    img = rgba(4, 4)
    img[0, 0, 3] = 50  # blurred halo
    img[0, 1] = (250, 250, 250, 180)  # white haze
    img[0, 2] = (250, 250, 250, 255)  # opaque white: part of the sprite
    out = ca.nettoyer(img)
    assert out[0, 0, 3] == 0 and out[0, 1, 3] == 0 and out[0, 2, 3] == 255
    assert set(np.unique(out[..., 3])) <= {0, 255}
    assert ca.nettoyer(img, voile=False)[0, 1, 3] == 255


def test_recadrer_on_opaque_pixels():
    img = np.zeros((10, 10, 4), np.uint8)
    img[2:5, 3:7] = 255
    assert ca.recadrer(img).shape == (3, 4, 4)
    assert ca.recadrer(np.zeros((3, 3, 4), np.uint8)).shape == (1, 1, 4)


def test_reduire_takes_dominant_color_without_blending():
    img = rgba(8, 8, (200, 0, 0))
    img[:, :3] = (0, 0, 200, 255)  # 3 blue columns of 8: red dominates in the right block
    out = ca.reduire(img, 2, 2)
    assert out.shape == (2, 2, 4)
    assert tuple(out[0, 1, :3]) == (200, 0, 0)
    assert tuple(out[0, 0, :3]) in {(0, 0, 200), (200, 0, 0)}  # no mixed purple
    sparse = np.zeros((4, 4, 4), np.uint8)
    sparse[0, 0] = 255  # 1 opaque pixel of 16: transparent once reduced
    assert ca.reduire(sparse, 1, 1)[0, 0, 3] == 0


def test_placer_anchors_bottom_center():
    out = ca.placer(rgba(2, 2), 6, 6, "bas")
    ys, xs = np.nonzero(out[..., 3])
    assert ys.max() == 5 and (xs.min(), xs.max()) == (2, 3)
    ys, _ = np.nonzero(ca.placer(rgba(2, 2), 6, 6, "centre")[..., 3])
    assert ys.min() == 2


def test_ranger_without_overlap():
    tailles = {f"f{i}": (30 + i % 7 * 10, 20 + i % 5 * 8) for i in range(40)}
    pos, w, h = ca.ranger(tailles, largeur=200)
    rects = [(x, y, x + tailles[n][0], y + tailles[n][1]) for n, (x, y) in pos.items()]
    for i, a in enumerate(rects):
        assert a[2] <= w and a[3] <= h
        for b in rects[i + 1 :]:
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


def manifeste(tmp_path):
    cut = tmp_path / "decoupe" / "p"
    cut.mkdir(parents=True)
    for n in range(1, 13):
        h = 20 + n * 4  # seedlings smaller than ripe plants
        Image.fromarray(rgba(h, 30)).save(cut / f"sprite_{n:03d}.png")
    m = {
        "version": "t",
        "modele": {
            "sante": {"sain": "healthy", "malade": "sick"},
            "stades": ["semis", "croissance", "floraison", "fructification", "recolte"],
        },
        "grid": {"tile_size": [16, 16]},
        "sources": {"p": {"cut_dir": "decoupe/p/", "file_pattern": "sprite_{n:03d}.png"}},
        "export": {"facteur": 2},
        "assets": {
            "characters": {
                "g": {
                    "size": [16, 24],
                    "animations": {
                        "walk_right": {"source": {"sheet": "p", "sprites": [1, 2]}},
                        "walk_left": {"flip_x": True, "miroir_de": "walk_right"},
                    },
                }
            },
            "plants": {
                "generic": {
                    "size": [16, 32],
                    "echelle_de": "tomato",
                    "source": {"sheet": "p", "sprites": [3]},
                },
                "tomato": {
                    "size": [16, 32],
                    "especes": ["tomate"],
                    "stades_modele": {"semis": 0, "recolte": 1},
                    "growth_stages": ["seedling", "ripe"],
                    "health_states": ["healthy", "sick"],
                    "source": {"sheet": "p", "sprites": [[3, 4], [5, 6]]},
                },
            },
            "containers": {
                "pot": {"type": "pot", "size": [16, 16], "source": {"sheet": "p", "sprites": [7]}}
            },
            "tiles": {
                "soil": {
                    "size": [16, 16],
                    "tileable": True,
                    "source": {"sheet": "p", "sprites": [8]},
                }
            },
            "devices": {
                "fan": {
                    "actuator": "ventilo",
                    "size": [16, 16],
                    "states": {"off": [9], "on": [10, 11]},
                    "source": {"sheet": "p", "sprites": [9, 10, 11]},
                }
            },
            "ui": {
                "box": {
                    "size": [32, 16],
                    "rendering": "nine_slice",
                    "source": {"sheet": "p", "sprites": [12]},
                },
                "todo": {"size": [16, 16]},
            },
        },
    }
    path = tmp_path / "sprites.json"
    path.write_text(json.dumps(m))
    return path


def test_construire_writes_atlas_and_catalogue(tmp_path):
    path = manifeste(tmp_path)
    out, cat_path = tmp_path / "public", tmp_path / "catalogue.json"
    r = ca.construire(path, out, cat_path, tmp_path / "apercu.png")
    assert r["assets"] == 7  # "todo" has no source
    hash_ = json.loads((out / "atlas.json").read_text())
    frames = hash_["frames"]
    assert {"plants/tomato/seedling/healthy", "devices/fan/on/1", "tiles/soil", "ui/box"} <= set(
        frames
    )
    assert Image.open(out / "atlas.png").size == (
        hash_["meta"]["size"]["w"],
        hash_["meta"]["size"]["h"],
    )
    assert (out / "ui" / "box.png").exists()

    # same scale for every stage: the seedling stays shorter than the ripe plant
    seedling = frames["plants/tomato/seedling/healthy"]["frame"]
    assert seedling["h"] == 64  # canvas = size × facteur
    tile = frames["tiles/soil"]["frame"]
    assert (tile["w"], tile["h"]) == (32, 32)

    cat = json.loads(cat_path.read_text())
    assert cat["facteur"] == 2 and cat["tuile"] == 16
    assert cat["plantes"]["especes"] == {"tomate": "tomato"}
    assert cat["plantes"]["generique"] == "plants/generic"
    assert cat["plantes"]["sprites"]["tomato"]["stades"]["recolte"] == {
        "sain": "plants/tomato/ripe/healthy",
        "malade": "plants/tomato/ripe/sick",
    }
    walk_left = cat["personnages"]["g"]["animations"]["walk_left"]
    assert walk_left["flip_x"] and walk_left["frames"] == [
        "characters/g/walk_right/0",
        "characters/g/walk_right/1",
    ]
    assert cat["actionneurs"]["ventilo"]["etats"]["on"] == ["devices/fan/on/0", "devices/fan/on/1"]
    assert cat["contenants"][0]["type"] == "pot"
    assert cat["ui"]["box"]["fichier"] == "sprites/ui/box.png"


def test_generic_plant_reuses_the_tomato_scale(tmp_path):
    path = manifeste(tmp_path)
    m = json.loads(path.read_text())
    images = ca.rendre(m, tmp_path, ca.lister_assets(m), 2)

    def height(n):
        ys = np.nonzero(images[n][..., 3])[0]
        return ys.max() - ys.min() + 1

    assert height("plants/generic") == height("plants/tomato/seedling/healthy")
    assert height("plants/tomato/seedling/healthy") < height("plants/tomato/ripe/sick")
