"""D8 — Cable routing: clips on the structure tube and wall bulkheads (docs/20 §4 D8).

- `clip_cables`: snaps on the tube (wrap 200°) and holds `nb_cables_clip` cables along it,
  each in its own snap cradle: cables off the wet floor, no pull on the connectors.
- `passe_paroi` + `circlip` + `joint_plat`: cable bulkhead through a wall of
  `paroi_traversee_ep` drilled at `passe_trou_d`. The flange and the TPU flat gasket stay
  outside, the printed circlip locks the sleeve inside, a TPU ring (`bague_cable`) in the
  flange seals around the cable. Leave a drip loop under every entry (docs/20 §7).
Material: ASA (sun) or PETG (inside), TPU gaskets and rings.
"""

from hardware.lib.commun import ORIG, V, Z, bague_tpu, boite, cyl, pince_tube, secteur

LARGEUR = 12.0
EP_BERCEAU = 1.6
EP_BRIDE = 3.0
EP_JOINT = 1.5
GORGE = 1.6  # circlip groove width
PROF_GORGE = 1.2


def clip_cables(p):
    r = (p.tube_d + p.jeu) / 2 + p.paroi
    c = pince_tube(p.tube_d + p.jeu, p.paroi, LARGEUR, enveloppe=200)
    d_c = p.cable_d + p.jeu
    pas = d_c + 2 * EP_BERCEAU + 0.5
    n = p.nb_cables_clip
    y_c = r + d_c / 2 + EP_BERCEAU - 0.6
    c = c.fuse(boite(n * pas, 2.0, LARGEUR, -n * pas / 2, r - 1.2, 0))  # below the cable holes
    berceaux = []
    for i in range(n):
        x = (i - (n - 1) / 2) * pas
        b = pince_tube(d_c, EP_BERCEAU, LARGEUR, enveloppe=220).rotated(ORIG, Z, 180)
        berceaux.append(b.translated(V(x, y_c, 0)))
    return c.fuse(berceaux).removeSplitter()


def _manchon_d(p):
    return p.passe_trou_d - p.jeu


def passe_paroi(p):
    d_m = _manchon_d(p)
    longueur = EP_JOINT + p.paroi_traversee_ep + 0.2 + GORGE + 2.5
    s = cyl(d_m + 10, EP_BRIDE).fuse(cyl(d_m, longueur, z=EP_BRIDE))
    z_gorge = EP_BRIDE + EP_JOINT + p.paroi_traversee_ep + 0.2
    gorge = cyl(d_m + 2, GORGE, z=z_gorge).cut(cyl(d_m - 2 * PROF_GORGE, GORGE + 2, z=z_gorge - 1))
    trou = cyl(p.cable_d + p.jeu, EP_BRIDE + longueur + 2, z=-1)
    chambrage = cyl(p.cable_d + 4 + p.jeu, 4.2, z=-0.01)  # TPU ring, outside face
    return s.cut([gorge, trou, chambrage]).removeSplitter()


def circlip(p):
    """Split ring snapped in the groove, pressing the sleeve against the wall."""
    r_int = (_manchon_d(p) - 2 * PROF_GORGE) / 2
    return secteur(r_int + 4, r_int, GORGE - 0.2, 290)


def joint_plat(p):
    d_m = _manchon_d(p)
    return cyl(d_m + 10, EP_JOINT).cut(cyl(d_m - 0.4, EP_JOINT + 2, z=-1))


def pieces(p):
    return {
        "clip_cables": clip_cables(p),
        "passe_paroi": passe_paroi(p),
        "circlip": circlip(p),
        "joint_plat": joint_plat(p),
        "bague_cable": bague_tpu(p.cable_d, p.cable_d + 4),
    }
