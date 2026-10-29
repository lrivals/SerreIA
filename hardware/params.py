"""Dimensions of the printed parts of the greenhouse (docs/20 §5.2) and the rules they must
respect (docs/20 §1, §4, §7).

Pure Python (no FreeCAD import): the dimensions are checked by the tests on any machine,
and `hardware/build.py` reads them inside FreeCAD. Every length is in millimetres.

The defaults are nominal values (datasheets, common sizes). The ones listed in `A_MESURER`
must be measured on the purchased hardware and written in `hardware/mesures.toml`, which
overrides them; the build warns while any of them is still nominal.
"""

import math
import tomllib
from dataclasses import dataclass, fields, replace
from pathlib import Path

MESURES = Path(__file__).with_name("mesures.toml")
VOLUME_IMPRESSION = 256.0  # Elegoo Centauri Carbon 2: 256 × 256 × 256 mm (docs/20 §2.1)


@dataclass(frozen=True)
class Params:
    # Printer: diametral clearance of a sliding fit, from the clearance rings (eprouvettes)
    jeu: float = 0.3
    paroi: float = 2.4  # default wall of the parts (6 perimeters of 0.4)

    # Structure (B1, B2, D4, D8, C2)
    tube_d: float = 20.0  # outer Ø of the structure tube
    tube_faitage_d: float = 20.0  # outer Ø of the ridge tube (lamp hooks)
    film_ep: float = 0.2  # PE film, 150–200 µm
    emmanchement: float = 32.0  # socket depth of a tube connector, >= 1.5 × Ø
    clip_enveloppe_deg: float = 210.0  # wrap angle of the film clip, 200–220°
    clip_largeur: float = 50.0  # 40–60 mm
    arete_r: float = 1.2  # edge radius on everything touching the film, >= 1 mm
    collier_l: float = 5.0  # cable-tie slot (width × 1.6 mm)

    # Fasteners
    insert_m3_d: float = 4.0  # hole for M3 heat-set brass inserts
    insert_m3_h: float = 5.7
    vis_m3_d: float = 3.4  # M3 clearance hole
    vis_m5_d: float = 5.5
    ecrou_m5_s: float = 8.0  # across flats of an M5 nut

    # Tank lid plate (A4): screwed on the existing tank lid, through a cut-out
    cuve_hauteur: float = 420.0  # inner height of the tank (60 L in serre.yaml)
    cuve_niveau_max: float = 160.0  # highest water level (overflow)
    platine_l: float = 220.0
    platine_w: float = 160.0
    platine_ep: float = 4.0
    sonde_ph_d: float = 12.0
    sonde_ec_d: float = 12.0
    ds18b20_d: float = 6.0
    jsn_d: float = 22.0  # JSN-SR04T transducer head
    jsn_rehausse: float = 0.0  # riser lifting the JSN-SR04T above the plate
    ecart_ph_ec: float = 60.0  # centre distance between the pH and EC probes
    trappe_d: float = 60.0  # filling hatch
    tuyau_dosage_d: float = 6.0  # 4/6 silicone tube of the dosing pumps
    tuyau_pompe_d: float = 16.0  # NFT pump feed / return

    # Node enclosure (D2): XIAO ESP32-C6 on a small carrier board
    carte_l: float = 50.0
    carte_w: float = 30.0
    carte_h: float = 15.0  # tallest component above the board
    cable_d: float = 5.0  # sensor cable through the glands
    antenne_d: float = 6.5  # RP-SMA bulkhead of the U.FL pigtail
    joint_l: float = 2.0  # TPU gasket groove width (depth 0.75 ×)

    # Radiation shield (D1)
    abri_d_int: float = 60.0  # SHT41 + BMP280 + SCD41 + XIAO
    abri_d_ext: float = 120.0
    abri_nb_assiettes: int = 6
    abri_pas: float = 14.0

    # Camera (D4): Raspberry Pi Camera Module 3, 25 × 24 mm, M2 holes 21 × 12.5
    cam_l: float = 25.0
    cam_w: float = 24.0
    cam_trous_x: float = 21.0
    cam_trous_y: float = 12.5
    cam_visiere: float = 30.0

    # Reference card (D5): grey / colour card, credit-card size
    mire_l: float = 85.6
    mire_w: float = 54.0
    mire_ep: float = 1.0
    mire_repere_pas: float = 10.0  # scale ticks for px -> cm² (docs/04 §5)

    # Lamp (C1, C2)
    profile_cote: float = 20.0  # 2020 aluminium profile
    cable_secu_d: float = 3.0  # steel safety cable (docs/20 §7)

    # Labels (E)
    etiquette_l: float = 60.0
    etiquette_w: float = 26.0  # QR v1 (21 modules) at >= 0.8 mm per module
    etiquette_ep: float = 2.0
    etiquette_texte_h: float = 8.0
    etiquette_relief: float = 0.8
    etiquette_piquet_l: float = 100.0
    police: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


# Field -> what to measure, on what (docs/20 §5.2).
A_MESURER = {
    "jeu": "clearance rings of hardware/pieces/eprouvettes.py, loosest ring that still slides",
    "tube_d": "structure tube, caliper at 3 places (ovality)",
    "tube_faitage_d": "ridge tube, caliper",
    "film_ep": "film datasheet",
    "cuve_hauteur": "tank, inner height",
    "cuve_niveau_max": "tank, height of the overflow / highest fill",
    "sonde_ph_d": "pH probe body, caliper",
    "sonde_ec_d": "EC probe body, caliper",
    "ds18b20_d": "DS18B20 waterproof sleeve, caliper",
    "jsn_d": "JSN-SR04T transducer head, caliper",
    "carte_l": "node carrier board with its connectors",
    "carte_w": "node carrier board with its connectors",
    "carte_h": "node carrier board, tallest component",
    "cable_d": "sensor cable",
    "profile_cote": "lamp upright (2020 profile or tube)",
}


def load(path: Path = MESURES) -> Params:
    """Nominal dimensions overridden by the measured ones of `path` (absent file: nominal)."""
    if not Path(path).exists():
        return Params()
    mesures = tomllib.loads(Path(path).read_text())
    known = {f.name: f.type for f in fields(Params)}
    unknown = sorted(set(mesures) - set(known))
    if unknown:
        raise ValueError(f"{path}: unknown dimensions {unknown}")
    return replace(Params(), **mesures)


def non_mesurees(path: Path = MESURES) -> list[str]:
    """Dimensions of `A_MESURER` still at their nominal value."""
    mesures = tomllib.loads(Path(path).read_text()) if Path(path).exists() else {}
    return [k for k in A_MESURER if k not in mesures]


def jsn_garde(p: Params) -> float:
    """Distance from the JSN-SR04T face to the highest water level."""
    return p.cuve_hauteur - p.cuve_niveau_max + p.platine_ep + p.jsn_rehausse


def verifier(p: Params) -> list[str]:
    """Rules of docs/20 the dimensions break; empty when the parts can be built."""
    err = []
    if not 0.1 <= p.jeu <= 0.5:
        err.append(f"jeu {p.jeu} mm outside 0.1–0.5 mm (re-print the clearance rings)")
    for nom in ("tube_d", "tube_faitage_d"):
        d = getattr(p, nom)
        if p.emmanchement < 1.5 * d:
            err.append(f"emmanchement {p.emmanchement} mm < 1.5 × {nom} ({1.5 * d:.1f} mm)")
    if jsn_garde(p) < 250:
        err.append(
            f"JSN-SR04T {jsn_garde(p):.0f} mm above the highest water, < 250 mm (blind zone):"
            " raise jsn_rehausse"
        )
    if p.ecart_ph_ec < 50:
        err.append(f"pH and EC probes {p.ecart_ph_ec} mm apart, < 50 mm")
    if not 200 <= p.clip_enveloppe_deg <= 220:
        err.append(f"clip wrap {p.clip_enveloppe_deg}° outside 200–220°")
    if p.arete_r < 1:
        err.append(f"edge radius {p.arete_r} mm < 1 mm (cuts the film)")
    for nom in ("platine_l", "platine_w", "abri_d_ext", "etiquette_piquet_l"):
        if getattr(p, nom) > VOLUME_IMPRESSION:
            err.append(f"{nom} {getattr(p, nom)} mm > printer volume {VOLUME_IMPRESSION:.0f} mm")
    if p.abri_d_int >= p.abri_d_ext - 2 * p.paroi:
        err.append("abri_d_int leaves no plate width")
    err += _chevauchements(disposition_couvercle(p), p.platine_l, p.platine_w, p.paroi)
    return err


def bossage_sonde(p: Params, d: float) -> float:
    """Outer Ø of a probe gland boss (hole + TPU ring + walls, lib/commun.passe_sonde)."""
    return d + 4 + 2 * p.paroi


def disposition_couvercle(p: Params) -> dict[str, tuple[float, float, float]]:
    """Holes of the tank lid plate (A4): name -> (x, y, footprint Ø), origin at a corner.

    Filling hatch on the left, pH / DS18B20 / EC in a row (the DS18B20 between them, for the
    temperature compensation), JSN-SR04T on the right, away from the probes in its beam,
    dosing tubes in a row along the front edge, pump tube at the back.
    """
    m = 15.0
    yc = p.platine_w / 2
    b_ph, b_ec = bossage_sonde(p, p.sonde_ph_d), bossage_sonde(p, p.sonde_ec_d)
    x_ph = 2 * m + p.trappe_d + b_ph / 2
    x_ec = x_ph + p.ecart_ph_ec
    b_jsn = p.jsn_d + 2 * p.paroi
    d = {
        "trappe": (m + p.trappe_d / 2, yc, p.trappe_d + 2 * p.paroi),
        "ph": (x_ph, yc + 15, b_ph),
        "ds18b20": ((x_ph + x_ec) / 2, yc + 15, bossage_sonde(p, p.ds18b20_d)),
        "ec": (x_ec, yc + 15, b_ec),
        "jsn": (p.platine_l - m - b_jsn / 2, yc, b_jsn),
        "pompe": (m + p.trappe_d / 2, p.platine_w - m, p.tuyau_pompe_d + p.jeu),
    }
    for i, nom in enumerate(("ph_down", "nutri_a", "nutri_b")):
        d[nom] = (x_ph + i * 3 * p.tuyau_dosage_d, m, p.tuyau_dosage_d + p.jeu)
    for i, (x, y) in enumerate(
        ((8, 8), (p.platine_l - 8, 8), (8, p.platine_w - 8), (p.platine_l - 8, p.platine_w - 8))
    ):
        d[f"fixation_{i}"] = (x, y, p.vis_m3_d)
    return d


def _chevauchements(trous: dict, lo: float, w: float, marge: float) -> list[str]:
    err = []
    noms = sorted(trous)
    for nom in noms:
        x, y, d = trous[nom]
        if x - d / 2 < marge / 2 or x + d / 2 > lo - marge / 2:
            err.append(f"tank lid: {nom} outside the plate in X")
        if y - d / 2 < marge / 2 or y + d / 2 > w - marge / 2:
            err.append(f"tank lid: {nom} outside the plate in Y")
    for i, a in enumerate(noms):
        for b in noms[i + 1 :]:
            (xa, ya, da), (xb, yb, db) = trous[a], trous[b]
            if math.hypot(xa - xb, ya - yb) < (da + db) / 2 + marge:
                err.append(f"tank lid: {a} and {b} overlap")
    return err
