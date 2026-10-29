"""B1 — Tube connectors at any angle (docs/20 §4 B1).

A hub with one socket per branch; each branch is (azimuth, elevation) in degrees. The tube
slides in with `jeu` and is pinned by an M5 stainless bolt across the socket (the bolt and
the tube carry the load, docs/20 §1). Socket depth `emmanchement` >= 1.5 × Ø (checked by
params.verifier). The tube stops against the hub.
`PRESETS` covers the usual nodes; add one for a new angle. The foot (`pied`) has a flange
with a central hole for the stake or threaded rod: the stake holds the wind, not the part.
Material: ASA (ASA-CF for the loaded nodes), 5–6 perimeters.
"""

import math

import Part

from hardware.lib.commun import V, Z, cyl

PENTE_TOIT = 30.0  # roof slope of the two-sided greenhouse (°)

PRESETS = {
    "coude_90": [(0, 0), (90, 0)],
    "te": [(0, 0), (180, 0), (90, 0)],
    "croix": [(0, 0), (90, 0), (180, 0), (270, 0)],
    "coin_3": [(0, 0), (90, 0), (0, 90)],  # box frame corner
    "te_poteau": [(0, 0), (180, 0), (0, -90)],  # wall plate on a post
    # ridge along Y, rafters going down both sides at PENTE_TOIT
    "faitage": [(90, 0), (270, 0), (0, -PENTE_TOIT), (180, -PENTE_TOIT)],
    "pied": [(0, 90)],
}


def direction(azimut: float, elevation: float):
    a, e = math.radians(azimut), math.radians(elevation)
    return V(math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e))


def raccord(p, branches: list[tuple[float, float]]):
    d_trou = p.tube_d + p.jeu
    d_ext = d_trou + 2 * 1.5 * p.paroi
    r0 = d_ext / 2  # tube stop, from the hub centre
    pleins, trous = [], []
    for az, el in branches:
        u = direction(az, el)
        pleins.append(cyl(d_ext, r0 + p.emmanchement, axe=u))
        e = u * r0
        trous.append(cyl(d_trou, p.emmanchement + 1, e.x, e.y, e.z, axe=u))
        # cross bolt in the middle of the socket, perpendicular to the branch
        perp = u.cross(Z) if abs(u.z) < 0.99 else V(1, 0, 0)
        perp.normalize()
        centre = u * (r0 + p.emmanchement / 2) - perp * (d_ext / 2 + 1)
        trous.append(cyl(p.vis_m5_d, d_ext + 2, centre.x, centre.y, centre.z, axe=perp))
    hub = Part.makeSphere(r0)
    s = hub.fuse(pleins)
    return s.cut(trous).removeSplitter()


def pieds(p):
    """Foot: vertical socket + flange (Ø 70) with a central hole for the stake / rod."""
    s = raccord(p, PRESETS["pied"])
    d_ext = p.tube_d + p.jeu + 3 * p.paroi
    bride = cyl(70, 5, z=-d_ext / 2)
    trous = [cyl(10.5, 20, z=-d_ext)]  # stake or M10 rod
    for i in range(3):
        a = math.radians(90 + 120 * i)
        trous.append(cyl(p.vis_m5_d, 20, 27 * math.cos(a), 27 * math.sin(a), -d_ext))
    return s.fuse(bride).cut(trous).removeSplitter()


def pieces(p):
    out = {nom: raccord(p, b) for nom, b in PRESETS.items() if nom != "pied"}
    out["pied"] = pieds(p)
    return out
