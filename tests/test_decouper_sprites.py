"""Automatic sprite detection (tools/decouper_sprites.py --auto), on synthetic sheets."""

import numpy as np

from tools import decouper_sprites as ds


def sheet(*rects):
    img = np.zeros((200, 300, 4), np.uint8)
    for x, y, w, h in rects:
        img[y : y + h, x : x + w] = (0, 128, 0, 255)
    return img


def test_object_overlapping_a_bigger_sprite_is_merged():
    # L-shaped gardener (box 60×120) and a bottle inside her box, 15 px from her pixels:
    # too far for the dilation, too big for a fragment
    img = sheet((20, 20, 20, 120), (20, 20, 60, 20))
    img[100:135, 55:75] = (0, 0, 200, 255)
    assert len(ds.detecter(img)) == 1


def test_neighbouring_sprites_stay_apart():
    assert len(ds.detecter(sheet((20, 20, 60, 120), (110, 20, 60, 120), (200, 80, 30, 40)))) == 3
