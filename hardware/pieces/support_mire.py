"""D5 — Holder of the grey / colour reference card (docs/20 §4 D).

The card stays in the camera field: fixed white balance (docs/05 §3) and px -> cm²
conversion of the growth tracking (docs/04 §5). The card slides in from one short side
between two lips; raised ticks every `mire_repere_pas` (long tick every 5) along the long
edges give the scale. A stake under the frame plants it in the pot or substrate; keep the
same distance and angle to the camera once placed. Material: matte ASA.
"""

from hardware.lib.commun import boite, boite_arrondie, piquet

CADRE = 6.0  # frame border
LEVRE = 1.5  # lip over the card


def cadre(p):
    lc = p.mire_l + 2 * CADRE
    w = p.mire_w + 2 * CADRE
    ep_fond = 2.0
    poche = p.mire_ep + 0.3
    h = ep_fond + poche + 1.2
    c = boite_arrondie(lc, w, h, 3, lc / 2, w / 2)
    # pocket open on the +X short side, lips on the long sides
    c = c.cut(
        boite(
            p.mire_l + CADRE + p.jeu + 1, p.mire_w + p.jeu, poche, CADRE, CADRE - p.jeu / 2, ep_fond
        )
    )
    c = c.cut(
        boite(p.mire_l + CADRE + 1, p.mire_w - 2 * LEVRE, h, CADRE + LEVRE, CADRE + LEVRE, ep_fond)
    )
    # scale ticks on the top of the long edges, from the card's left edge
    n = int(p.mire_l // p.mire_repere_pas)
    traits = []
    for i in range(n + 1):
        x = CADRE + i * p.mire_repere_pas - 0.3
        long = 4.0 if i % 5 == 0 else 2.0
        traits += [boite(0.6, long, 0.6, x, 0.5, h), boite(0.6, long, 0.6, x, w - 0.5 - long, h)]
    c = c.fuse(traits)
    # stake under the frame (point at the end)
    return c.fuse(piquet(8, 103, 4, lc / 2, 3)).removeSplitter()


def pieces(p):
    return {"cadre": cadre(p)}
