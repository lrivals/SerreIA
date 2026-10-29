"""C1 (variant) — Lamp corners on M8 threaded rods, set to the millimetre (docs/20 §4 C1).

One stainless M8 rod per corner, hanging from the structure (`fixation_tige`: clamp on
the tube, the rod nut bears on the block). Each lamp corner (`equerre`) rests on a knob
with a captive M8 nut (`molette`), a second knob above locks it: turn the knobs by the same
number of turns at the four corners and the lamp stays level (1.25 mm per turn).
The rods only position the lamp: a steel safety cable holds it (docs/20 §7).
Material: PETG-CF or ASA-CF; ASA within 5 cm of the LED driver.
"""

from hardware.lib.commun import ORIG, X, Y, boite, cyl, hexagone, molette_hex, pince_tube

EP_PATTE = 6.0


def equerre(p):
    """Corner block on the rod + tab with two M5 holes for the lamp bar."""
    b = boite(30, 30, 14, centre=True)
    b = b.fuse(boite(40, 30, EP_PATTE, 14, -15, 0))
    trous = [cyl(p.tige_m8_d + p.jeu, 16, z=-1)]
    trous += [cyl(p.vis_m5_d, EP_PATTE + 2, x, 0, -1) for x in (28, 46)]
    return b.cut(trous).removeSplitter()


def molette(p):
    return molette_hex(32, 10, p.ecrou_m8_s + p.jeu, 6.5, p.tige_m8_d)


def fixation_tige(p):
    """Clamp hanging on a horizontal tube (closed side up), M8 rod beside the tube."""
    largeur = 16.0
    r = (p.tube_d + p.jeu) / 2 + 1.5 * p.paroi
    c = pince_tube(p.tube_d + p.jeu, 1.5 * p.paroi, largeur, enveloppe=210)
    c = c.rotated(ORIG, Y, 90).rotated(ORIG, X, 90)  # tube along X, opening down (-Z)
    bloc = boite(largeur, 18, 16, 0, r - 1, -8)
    y_tige = r + 8
    trous = [
        cyl(p.tige_m8_d + p.jeu, 20, largeur / 2, y_tige, -10),
        hexagone(p.ecrou_m8_s + p.jeu, 6.6, largeur / 2, y_tige, 8 - 6.5),
    ]
    return c.fuse(bloc).cut(trous).removeSplitter()


def pieces(p):
    return {"equerre": equerre(p), "molette": molette(p), "fixation_tige": fixation_tige(p)}
