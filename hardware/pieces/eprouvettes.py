"""Test pieces printed before any tight fit (docs/20 §1, §5.2).

- `anneaux_jeu`: rings of inner Ø tube_d + 0.1 … 0.5 mm, 5 mm high, to slide on the real
  tube; the number of notches on the rim gives the clearance in tenths. The loosest ring
  that still slides without play gives `jeu` in mesures.toml.
- `tranche_clip`: 5 mm slice of the film clip (B2), to check the snap on tube + film.
- `inserts_m3`: three holes at insert_m3_d - 0.1 / ± 0 / + 0.1 for the brass inserts.
- `gabarit_sondes`: plate with every probe / cable hole at its nominal Ø + jeu (PLA allowed:
  measuring tool, never installed in the greenhouse).
"""

from hardware.lib.commun import bague_tpu, boite, cyl, tube
from hardware.pieces import clip_bache

JEUX = (0.1, 0.2, 0.3, 0.4, 0.5)


def anneaux_jeu(p):
    d_ext = p.tube_d + 0.5 + 2 * p.paroi
    pas = d_ext + 4
    anneaux = []
    for i, j in enumerate(JEUX):
        x = i * pas
        a = tube(d_ext, p.tube_d + j, 5, x)
        for k in range(i + 1):  # notches on the rim: 1 = 0.1 mm … 5 = 0.5 mm
            a = a.cut(boite(1.2, 3, 1.2, x - 0.6 + (k - i / 2) * 2.4, d_ext / 2 - 2, 3.9))
        anneaux.append(a)
    return anneaux[0].fuse(anneaux[1:])


def inserts_m3(p):
    bloc = boite(36, 12, p.insert_m3_h + 3)
    for i, dd in enumerate((-0.1, 0.0, 0.1)):
        bloc = bloc.cut(cyl(p.insert_m3_d + dd, p.insert_m3_h + 1, 6 + i * 12, 6, 3))
        bloc = bloc.cut(boite(1, 3, 0.6, 5.5 + i * 12 - i * 0.8, 0, p.insert_m3_h + 2.4))
    return bloc


def gabarit_sondes(p):
    diametres = [
        p.sonde_ph_d,
        p.sonde_ec_d,
        p.ds18b20_d,
        p.jsn_d,
        p.cable_d,
        p.tuyau_dosage_d,
        p.tuyau_pompe_d,
    ]
    x, trous = 6.0, []
    for d in diametres:
        trous.append((x + d / 2, d))
        x += d + 6
    plaque = boite(x, max(diametres) + 12, 3)
    for cx, d in trous:
        plaque = plaque.cut(cyl(d + p.jeu, 5, cx, (max(diametres) + 12) / 2, -1))
    return plaque


def pieces(p):
    return {
        "anneaux_jeu": anneaux_jeu(p),
        "tranche_clip": clip_bache.clip(p, largeur=5),
        "inserts_m3": inserts_m3(p),
        "gabarit_sondes": gabarit_sondes(p),
        "bague_tpu_ph": bague_tpu(p.sonde_ph_d, p.sonde_ph_d + 4),
    }
