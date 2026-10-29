"""C1 (variant) — Notched rack: lamp height in steps of `cran_pas`, without tools
(docs/20 §4 C1).

The rack (`barre`) is screwed on the upright (2 × M5), slots every `cran_pas`; on a tall
upright, several bars end to end keep the pitch (half a pitch at each end). The hook
(`crochet`) enters a slot, drops and hangs behind the bar under the lamp weight; to move
it, lift and pull. Same slot number at every upright = level lamp.
The rack only positions the lamp: a steel safety cable holds it (docs/20 §7).
Material: PETG-CF or ASA-CF; ASA within 5 cm of the LED driver.
"""

from hardware.lib.commun import X, boite, cyl

LARGEUR = 20.0
EP_BARRE = 6.0
FENTE_L, FENTE_W = 12.0, 4.0  # slot along the bar × across
LANGUE_W, LANGUE_EP, LEVRE = 3.4, 3.0, 6.0  # hook tongue width, thickness, lip length


def fentes(p) -> list[float]:
    """Slot centres along the bar (x), half a pitch from the ends."""
    n = int((p.cremaillere_l - p.cran_pas / 2) // p.cran_pas) + 1
    return [
        p.cran_pas / 2 + i * p.cran_pas
        for i in range(n)
        if p.cran_pas / 2 + i * p.cran_pas + FENTE_L / 2 <= p.cremaillere_l - 3
    ]


def barre(p):
    b = boite(p.cremaillere_l, LARGEUR, EP_BARRE)
    trous = [
        boite(FENTE_L, FENTE_W, EP_BARRE + 2, x - FENTE_L / 2, (LARGEUR - FENTE_W) / 2, -1)
        for x in fentes(p)
    ]
    # M5 screws between the first two and the last two slots
    xs = fentes(p)
    for xa, xb in ((xs[0], xs[1]), (xs[-2], xs[-1])):
        trous.append(cyl(p.vis_m5_d, EP_BARRE + 2, (xa + xb) / 2, LARGEUR / 2, -1))
    return b.cut(trous).removeSplitter()


def crochet(p):
    """Frame of the bar: front face z = 0, bar behind (z < 0), x up. Plate against the
    front, tongue through a slot, lip behind the bar pointing down (-x), lamp tab standing
    out (+z) with two M5 holes. Tongue + lip (9 mm) pass the 12 mm slot."""
    plaque = boite(40, LARGEUR, 5, -20, 0, 0)
    y0 = (LARGEUR - LANGUE_W) / 2
    z_dos = -(EP_BARRE + 0.4)
    langue = boite(LANGUE_EP, LANGUE_W, -z_dos + 0.5, 0, y0, z_dos)
    levre = boite(LEVRE + LANGUE_EP, LANGUE_W, 2.4, -LEVRE, y0, z_dos - 2.4)
    patte = boite(6, LARGEUR, 40, 14, 0, 4.5)
    s = plaque.fuse([langue, levre, patte])
    s = s.cut([cyl(p.vis_m5_d, 8, 13, LARGEUR / 2, z, axe=X) for z in (20, 36)])
    return s.removeSplitter()


def pieces(p):
    return {"barre": barre(p), "crochet": crochet(p)}
