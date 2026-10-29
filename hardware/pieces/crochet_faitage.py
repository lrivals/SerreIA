"""C2 — Hooks and spreader bar for the ratchet hangers of the lamps (docs/20 §4 C2).

The ratchet hangers are bought (rated load); only their attachment is printed:
- `crochet`: snaps on the ridge tube (wrap 200°) with an eye below for the hanger hook;
- `palonnier`: bar spreading one hanger on two lamp points;
- `guide_cable`: clip keeping the steel safety cable along the ridge. The safety cable
  loops around the tube itself, never through a printed part (docs/20 §7).
Material: ASA (sun, heat of the lamp), PETG-CF for the spreader bar.
"""

from hardware.lib.commun import boite, cyl, pince_tube, tube

LARGEUR = 14.0
D_OEIL = 10.0  # hole for the hanger hook / carabiner


def crochet(p):
    d = p.tube_faitage_d + p.jeu
    ep = 2 * p.paroi
    c = pince_tube(d, ep, LARGEUR, enveloppe=200)
    # the clip opens towards -Y: hang it with the opening up, the eye goes on +Y (down)
    r = d / 2 + ep
    patte = boite(LARGEUR, 12 + D_OEIL, LARGEUR, -LARGEUR / 2, r - 2, 0)
    oeil = cyl(D_OEIL + 2 * ep + 2, LARGEUR, 0, r + 8 + D_OEIL / 2)
    c = c.fuse([patte, oeil]).cut(cyl(D_OEIL, LARGEUR + 2, 0, r + 8 + D_OEIL / 2, -1))
    return c.removeSplitter()


def palonnier(p, entraxe: float = 200.0):
    """Bar of `entraxe` between the two lamp holes, central eye for the hanger."""
    ep = 8.0
    b = boite(entraxe + 20, 16, ep, -(entraxe + 20) / 2, -8, 0)
    b = b.fuse(cyl(28, ep))
    trous = [cyl(D_OEIL, ep + 2, z=-1)]
    trous += [cyl(6.5, ep + 2, sx * entraxe / 2, 0, -1) for sx in (-1, 1)]
    return b.cut(trous).removeSplitter()


def guide_cable(p):
    d = p.tube_faitage_d + p.jeu
    c = pince_tube(d, p.paroi, 10, enveloppe=210)
    r = d / 2 + p.paroi
    oeil = tube(p.cable_secu_d + 1 + 2 * p.paroi, p.cable_secu_d + 1, 10, 0, r + 3)
    return c.fuse(oeil).removeSplitter()


def pieces(p):
    return {"crochet": crochet(p), "palonnier": palonnier(p), "guide_cable": guide_cable(p)}
