"""A4 — Tank lid plate and probe holders (docs/20 §4 A4, docs/06 §1.2).

The plate is screwed (4 × M3 stainless) over a cut-out of the existing tank lid. Positions
come from `params.disposition_couvercle` (checked by `params.verifier`): pH and EC probes
apart, the DS18B20 between them, the JSN-SR04T vertical and away from the probes, at least
250 mm above the highest water level (raise `jsn_rehausse` otherwise).

Probe depth: each probe slides in its gland and is held by a TPU ring (`bague_*`), pushed
down to the depth where the bulb is immersed without touching the bottom.
Material: opaque PETG, TPU rings (docs/20 §2.2).
"""

from hardware.lib.commun import bague_tpu, boite_arrondie, cyl, passe_sonde, tube
from hardware.params import disposition_couvercle

H_BOSSAGE = 12.0


def platine(p):
    t = disposition_couvercle(p)
    pl = boite_arrondie(p.platine_l, p.platine_w, p.platine_ep, 6, p.platine_l / 2, p.platine_w / 2)
    trous = []
    for nom, d in (("ph", p.sonde_ph_d), ("ec", p.sonde_ec_d), ("ds18b20", p.ds18b20_d)):
        x, y, _ = t[nom]
        bossage, trou = passe_sonde(d, p.jeu, p.paroi, p.platine_ep + H_BOSSAGE, x, y)
        pl = pl.fuse(bossage)
        trous.append(trou)
    # JSN-SR04T: the transducer head is pushed into a vertical sleeve (+ optional riser)
    x, y, b = t["jsn"]
    h_jsn = p.platine_ep + 15 + p.jsn_rehausse
    pl = pl.fuse(cyl(b, h_jsn, x, y))
    trous.append(cyl(p.jsn_d + p.jeu, h_jsn + 2, x, y, -1))
    # Filling hatch: a lip around the hole holds the plug
    x, y, b = t["trappe"]
    pl = pl.fuse(tube(b, p.trappe_d, p.platine_ep + 6, x, y))
    trous.append(cyl(p.trappe_d, p.platine_ep + 10, x, y, -1))
    for nom in (
        "pompe",
        "ph_down",
        "nutri_a",
        "nutri_b",
        "fixation_0",
        "fixation_1",
        "fixation_2",
        "fixation_3",
    ):
        x, y, d = t[nom]
        trous.append(cyl(d, p.platine_ep + 2, x, y, -1))
    return pl.cut(trous).removeSplitter()


def bouchon_trappe(p):
    """Plug of the filling hatch: sits on the lip, a finger tab to lift it."""
    b = cyl(p.trappe_d + 2 * p.paroi + 4, 3).fuse(cyl(p.trappe_d - p.jeu, 9, z=-6))
    b = b.cut(cyl(p.trappe_d - p.jeu - 2 * p.paroi, 7, z=-7))
    return b.fuse(boite_arrondie(20, 6, 8, 2, 0, 0, 3)).removeSplitter()


def pieces(p):
    return {
        "platine": platine(p),
        "bouchon_trappe": bouchon_trappe(p),
        "bague_ph": bague_tpu(p.sonde_ph_d, p.sonde_ph_d + 4),
        "bague_ec": bague_tpu(p.sonde_ec_d, p.sonde_ec_d + 4),
        "bague_ds18b20": bague_tpu(p.ds18b20_d, p.ds18b20_d + 4),
    }
