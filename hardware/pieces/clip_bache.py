"""B2 — Clip holding the PE film on a tube, and the TPU pad under the film (docs/20 §4 B2).

The clip snaps on tube + film (inner Ø = tube_d + 2 × film_ep, no clearance: it must
grip), wraps `clip_enveloppe_deg`, and has a tunnel at the back for a cable tie looped
around the tube. Every edge touching the film is rounded (`arete_r`). Spacing about
50–60 cm, closer at the corners. Print the layers across the opening of the C (a clip
that opens breaks between two layers): lay it on its side. Material: ASA.
The pad (`patin_tpu`) is a thin TPU sleeve between tube and film where the film rubs.
"""

from hardware.lib.commun import arrondir, boite, pince_tube

LONGUEUR_TUNNEL = 10.0


def clip(p, largeur: float | None = None):
    """Clip along Z (from 0 to `largeur`); narrower than the tie: no tunnel (test slice)."""
    largeur = p.clip_largeur if largeur is None else largeur
    d = p.tube_d + 2 * p.film_ep
    ep = 1.5 * p.paroi
    c = arrondir(pince_tube(d, ep, largeur, p.clip_enveloppe_deg), p.arete_r)
    hz = p.collier_l + 2 * 1.6
    if largeur < hz:
        return c
    # cable-tie tunnel on the back (+Y), tangent to the tube (the tie loops in the XY plane)
    r = d / 2 + ep
    z0 = (largeur - hz) / 2
    bosse = boite(LONGUEUR_TUNNEL, 1.6 + 2 * 1.2 + 1, hz, -LONGUEUR_TUNNEL / 2, r - 1, z0)
    tunnel = boite(
        LONGUEUR_TUNNEL + 2, 1.6, p.collier_l + 0.4, -LONGUEUR_TUNNEL / 2 - 1, r + 0.2, z0 + 1.4
    )
    return c.fuse(bosse).cut(tunnel).removeSplitter()


def patin(p):
    return pince_tube(p.tube_d + p.jeu, 1.2, 40, enveloppe=240)


def pieces(p):
    return {"clip": clip(p), "patin_tpu": patin(p)}
