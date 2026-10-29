"""C1 — Lamp slider on an upright (docs/20 §4 C1).

A sleeve sliding on a 2020 aluminium profile (or a square tube of side `profile_cote`),
locked by an M5 stainless bolt screwed in a captive nut and turned by a printed knob; a tab
with two M5 holes carries the lamp bar. One slider per upright: the lamp stays level when
every slider is set to the same height (mark the uprights every cm).
The slider only positions the lamp: a steel safety cable holds it (docs/20 §7).
Material: PETG-CF or ASA-CF; ASA within 5 cm of the LED driver.
"""

import math

from hardware.lib.commun import ORIG, V, X, Y, boite, cyl, hexagone

H = 40.0  # sleeve height
EP = 4.0  # sleeve wall
LG_PATTE = 40.0  # lamp tab length
EP_ECROU = 4.5  # M5 nut thickness + play


def coulisseau(p):
    c_int = p.profile_cote + p.jeu + 0.4  # slides freely, the bolt takes up the play
    c_ext = c_int + 2 * EP
    s = boite(c_ext, c_ext, H, centre=True)
    s = s.cut(boite(c_int, c_int, H + 2, 0, 0, -1, centre=True))
    # bolt boss on +X, captive M5 nut inserted from the top
    x0 = c_ext / 2 - 1
    s = s.fuse(boite(8, 14, 14, x0, -7, H / 2 - 7))
    s_ecrou = p.ecrou_m5_s + p.jeu
    trous = [
        cyl(p.vis_m5_d, 14, c_int / 2 - 1, 0, H / 2, axe=X),
        hexagone(s_ecrou, EP_ECROU).rotated(ORIG, Y, 90).translated(V(x0 + 2, 0, H / 2)),
        boite(EP_ECROU, s_ecrou, 8, x0 + 2, -s_ecrou / 2, H / 2),
    ]
    s = s.cut(trous)
    # lamp tab on -X
    patte = boite(LG_PATTE, c_ext, 6, -c_ext / 2 - LG_PATTE + 1, -c_ext / 2, 0)
    patte = patte.cut([cyl(p.vis_m5_d, 8, -c_ext / 2 - dx, 0, -1) for dx in (12, 30)])
    return s.fuse(patte).removeSplitter()


def molette(p):
    """Knob: the hex head of an M5 bolt pressed in a pocket, ribs for the grip."""
    m = cyl(26, 10)
    m = m.cut(
        [
            cyl(4, 12, 13 * math.cos(a), 13 * math.sin(a), -1)
            for a in (math.radians(30 * i) for i in range(12))
        ]
    )
    m = m.cut(hexagone(p.ecrou_m5_s + p.jeu, 4.01, 0, 0, 6))
    return m.cut(cyl(p.vis_m5_d, 12, z=-1)).removeSplitter()


def pieces(p):
    return {"coulisseau": coulisseau(p), "molette": molette(p)}
