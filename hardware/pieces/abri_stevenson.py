"""D1 — Ventilated radiation shield for SHT41, BMP280 and SCD41 (docs/20 §4 D, docs/06 §1.2).

A stack of conical plates sloping down outwards (rain and direct sun stay out, air flows
between them), held by 3 stainless M3 threaded rods through the spacer posts; a solid roof
on top, a bracket under the stack clamps on the structure tube.
Print `abri_nb_assiettes` plates, one roof, one bracket. Material: white ASA, thick walls
(the filament lets infrared through, docs/20 §2.2).
"""

import math

import Part

from hardware.lib.commun import V, Z, boite, cyl, pince_tube

PENTE = math.tan(math.radians(20))


def _geometrie(p):
    r_ext, r_int = p.abri_d_ext / 2, p.abri_d_int / 2
    hc = (r_ext - r_int) * PENTE
    r_poteau = r_int + 7
    return r_ext, r_int, hc, r_poteau


def _plateau(p, ouvert: bool, poteaux: bool):
    r_ext, r_int, hc, r_poteau = _geometrie(p)
    ep = p.paroi
    cone = Part.makeCone(r_ext, r_int, hc, V(0, 0, 0), Z)
    s = cone.cut(cone.translated(V(0, 0, -ep)))
    if not ouvert:  # roof: closed by a disc at the top of the cone
        s = s.fuse(cyl(2 * r_int, ep, z=hc - ep))
    else:
        s = s.cut(cyl(2 * r_int, hc + 2, z=-1))
    z_poteau = hc * (r_ext - r_poteau) / (r_ext - r_int) - ep
    for i in range(3):
        a = math.radians(90 + 120 * i)
        x, y = r_poteau * math.cos(a), r_poteau * math.sin(a)
        if poteaux:
            s = s.fuse(cyl(8, p.abri_pas, x, y, z_poteau))
        s = s.cut(cyl(p.vis_m3_d, p.abri_pas + hc + 10, x, y, -5))
    return s.removeSplitter()


def support(p):
    """Bracket under the stack: a ring with the 3 rod holes and an arm to the tube clamp."""
    r_ext, r_int, _, r_poteau = _geometrie(p)
    ep = 5.0
    s = cyl(2 * r_poteau + 14, ep).cut(cyl(2 * r_int - 6, ep + 2, z=-1))
    longueur = r_ext + p.tube_d / 2 + 10
    s = s.fuse(boite(longueur - r_poteau, 16, ep, r_poteau, -8, 0))
    pince = pince_tube(p.tube_d + p.jeu, 1.5 * p.paroi, 16, enveloppe=200)
    pince = pince.rotated(
        V(0, 0, 0), V(0, 1, 0), 90
    )  # tube axis along Y, opening away from the arm
    pince = pince.rotated(V(0, 0, 0), Z, 90).translated(V(longueur + p.tube_d / 2, -8, ep / 2))
    s = s.fuse(pince)
    for i in range(3):
        a = math.radians(90 + 120 * i)
        s = s.cut(cyl(p.vis_m3_d, ep + 2, r_poteau * math.cos(a), r_poteau * math.sin(a), -1))
    return s.removeSplitter()


def pieces(p):
    return {
        "assiette": _plateau(p, ouvert=True, poteaux=True),
        "toit": _plateau(p, ouvert=False, poteaux=False),
        "support": support(p),
    }
