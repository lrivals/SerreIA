"""D2 — Enclosure of a XIAO ESP32-C6 sensor node (docs/20 §4 D, docs/06).

Box + lid screwed on 4 brass inserts, with a printed TPU gasket in a groove of the lid.
Mounted vertically: the cable glands are in the bottom face (cables enter from below, drip
loop under the box), with a 2 mm vent at the lowest point to drain the condensation; the
RP-SMA bulkhead of the U.FL antenna goes through the top face. Two lugs at the back take
cable ties or screws on the structure.
Material: PETG or ASA, TPU gasket and rings (docs/20 §2.2).
"""

from hardware.lib.commun import Y, bague_tpu, boite, boite_arrondie, cyl, trou_insert_m3

JEU_CARTE = 4.0  # free space around the board (wires, connectors)
NB_PRESSE_ETOUPES = 2


def _dimensions(p):
    e = max(p.paroi, p.joint_l + 2 * 1.2)  # wall wide enough for the gasket groove
    li = p.carte_l + 2 * JEU_CARTE + 12  # + room for the 4 corner bosses
    wi = p.carte_w + 2 * JEU_CARTE + 12
    hi = p.carte_h + 8
    return e, li, wi, hi


def _coins(li, wi):
    return [(sx * (li / 2 - 4), sy * (wi / 2 - 4)) for sx in (-1, 1) for sy in (-1, 1)]


def boite_noeud(p):
    e, li, wi, hi = _dimensions(p)
    b = boite_arrondie(li + 2 * e, wi + 2 * e, hi + e, 3)
    b = b.cut(boite_arrondie(li, wi, hi + 1, 1, 0, 0, e))
    for x, y in _coins(li, wi):  # lid bosses with inserts
        b = b.fuse(cyl(8, hi, x, y, e)).cut(trou_insert_m3(p, x, y, hi + e))
    for x, y in ((-p.carte_l / 2 + 3, -p.carte_w / 2 + 3), (p.carte_l / 2 - 3, p.carte_w / 2 - 3)):
        b = b.fuse(cyl(6, 4, x, y, e)).cut(trou_insert_m3(p, x, y, e + 4))  # board standoffs
    # bottom face (-Y): cable glands with an outer boss for the TPU ring, vent at the floor
    y_bas = -(wi / 2 + e)
    for i in range(NB_PRESSE_ETOUPES):
        x = (i - (NB_PRESSE_ETOUPES - 1) / 2) * (p.cable_d + 14)
        z = e + hi / 2
        b = b.fuse(cyl(p.cable_d + 4 + 2 * p.paroi, 5, x, y_bas, z, axe=Y * -1))
        b = b.cut(cyl(p.cable_d + p.jeu, e + 12, x, y_bas - 6, z, axe=Y))
        b = b.cut(cyl(p.cable_d + 4 + p.jeu, 4.2, x, y_bas - 5.01, z, axe=Y))
    b = b.cut(cyl(2, e + 2, 0, y_bas - 1, e + 1, axe=Y))  # between the glands
    # top face (+Y): antenna bulkhead
    b = b.cut(cyl(p.antenne_d, e + 2, 0, wi / 2 - 1, e + hi / 2, axe=Y))
    # back lugs (on the floor side, -Z), for cable ties around the tube or screws
    for sx in (-1, 1):
        x = sx * (li / 2 + e + 6)
        b = b.fuse(boite(12, 20, 4, x - 6, -10, 0)).cut(cyl(p.vis_m3_d + 1, 6, x, 0, -1))
    return b.removeSplitter()


def couvercle(p):
    e, li, wi, hi = _dimensions(p)
    c = boite_arrondie(li + 2 * e, wi + 2 * e, e, 3)
    for x, y in _coins(li, wi):
        c = c.cut(cyl(p.vis_m3_d, e + 2, x, y, -1))
    # gasket groove on the inner face (z = 0), on the middle of the box wall
    prof = 0.75 * p.joint_l
    lg, wg = li + e, wi + e  # groove centreline
    rainure = boite_arrondie(lg + p.joint_l, wg + p.joint_l, prof, 2.5).cut(
        boite_arrondie(lg - p.joint_l, wg - p.joint_l, prof + 2, 1.5, 0, 0, -1)
    )
    return c.cut(rainure).removeSplitter()


def joint(p):
    """TPU gasket: groove section, 0.5 mm higher than the groove (compressed by the lid)."""
    e, li, wi, _ = _dimensions(p)
    lg, wg = li + e, wi + e
    lj = p.joint_l - 0.2
    return boite_arrondie(lg + lj, wg + lj, 0.75 * p.joint_l + 0.5, 2.5).cut(
        boite_arrondie(lg - lj, wg - lj, 5, 1.5, 0, 0, -1)
    )


def pieces(p):
    return {
        "boite": boite_noeud(p),
        "couvercle": couvercle(p),
        "joint": joint(p),
        "bague_cable": bague_tpu(p.cable_d, p.cable_d + 4),
    }
