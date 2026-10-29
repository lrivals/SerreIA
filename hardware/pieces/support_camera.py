"""D4 — Fixed-angle mount of a Raspberry Pi Camera Module 3 (docs/20 §4 D, docs/09 §4).

The vision assumes a stable framing (one region per emplacement): the tilt is locked, not
only clamped. The tube clamp carries a graduated ear with a ring of holes every `PAS_DEG`;
the camera housing carries a matching ear with its centre hole and one locking hole. An M3
bolt through the centres clamps, a second M3 bolt through the chosen hole locks the angle.
Write the angle read on the scale in the camera description.
The housing has a recess for a 2 mm glass / PMMA window and a visor against condensation
drips. Material: ASA.
"""

import math

from hardware.lib.commun import ORIG, V, Y, boite, cyl, graduations, pince_tube

PAS_DEG = 15.0
R_OREILLE = 18.0
R_TROUS = 12.0
EP_OREILLE = 5.0
FENETRE = 20.0  # side of the square glass / PMMA window
BRAS = 28.0


def _oreille_yz(oreille, x, y, z):
    """Ear drawn in the XY plane -> plane YZ (tilt axis along X), thickness from x."""
    return oreille.rotated(ORIG, Y, 90).translated(V(x, y, z))


def pince(p):
    """Tube clamp (tube along X) + arm along +Y + graduated ear (tilt axis along X)."""
    largeur = 16.0
    r = (p.tube_d + p.jeu) / 2 + 1.5 * p.paroi
    c = pince_tube(p.tube_d + p.jeu, 1.5 * p.paroi, largeur, enveloppe=210)
    c = c.rotated(ORIG, Y, 90)  # tube along X (x from 0 to largeur), opening towards -Y
    bras = boite(largeur, BRAS + 2, EP_OREILLE, 0, r - 2, -EP_OREILLE / 2)
    oreille = cyl(2 * R_OREILLE, EP_OREILLE)
    oreille = oreille.fuse(graduations(R_OREILLE, PAS_DEG, 0.6, -90, 90, EP_OREILLE))
    trous = [cyl(3.4, EP_OREILLE + 2, z=-1)]
    for i in range(int(180 / PAS_DEG) + 1):
        a = math.radians(-90 + i * PAS_DEG)
        trous.append(cyl(3.4, EP_OREILLE + 2, R_TROUS * math.cos(a), R_TROUS * math.sin(a), -1))
    oreille = oreille.cut(trous)
    y_axe = r + BRAS + R_OREILLE - 4
    oreille = _oreille_yz(oreille, largeur / 2 - EP_OREILLE / 2, y_axe, 0)
    return c.fuse([bras, oreille]).removeSplitter()


def boitier(p):
    """Camera housing (lens along -Z): board on 4 M2 holes, window, visor, locking ear."""
    e = p.paroi
    lb, w, prof = p.cam_l + 2 * e + 2, p.cam_w + 2 * e + 2, 14.0
    b = boite(lb, w, prof, centre=True)
    b = b.cut(boite(lb - 2 * e, w - 2 * e, prof, 0, 0, e, centre=True))  # open back
    b = b.cut(cyl(14, e + 2, z=-1))  # lens
    b = b.cut(boite(FENETRE + 0.4, FENETRE + 0.4, 2.2, 0, 0, -0.01, centre=True))  # window
    for sx in (-1, 1):
        for sy in (-1, 1):
            x, y = sx * p.cam_trous_x / 2, sy * p.cam_trous_y / 2
            b = b.fuse(cyl(4.5, 4, x, y, e)).cut(cyl(1.8, 6, x, y, e - 1))  # M2 self-tapping
    # visor: roof and half cheeks in front of the window
    v = p.cam_visiere
    b = b.fuse(boite(lb, e, v, -lb / 2, w / 2 - e, -v))
    b = b.fuse([boite(e, w / 2, v, -lb / 2, 0, -v), boite(e, w / 2, v, lb / 2 - e, 0, -v)])
    # ear on the +X side: centre hole, one locking hole, index mark facing the scale
    oreille = cyl(2 * R_OREILLE, EP_OREILLE)
    oreille = oreille.cut(
        [cyl(3.4, EP_OREILLE + 2, z=-1), cyl(3.4, EP_OREILLE + 2, R_TROUS, 0, -1)]
    )
    oreille = oreille.fuse(boite(3, 0.8, 0.6, R_OREILLE - 3, -0.4, EP_OREILLE))
    b = b.fuse(_oreille_yz(oreille, lb / 2, 0, prof / 2))
    return b.removeSplitter()


def pieces(p):
    return {"pince": pince(p), "boitier": boitier(p)}
