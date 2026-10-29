"""E — Emplacement labels: code in relief + QR code, on a stake (docs/20 §4 E).

Reads the labels written by `python -m tools.hardware.etiquettes` (hardware/build/
etiquettes.json, or $SERREIA_ETIQUETTES); without that file, one sample label `z1-A1`.
The text and the QR modules stand `etiquette_relief` above the plate: with the CANVAS
combo, change the colour at that height (dark relief on a light plate, readable QR).
Material: ASA.
"""

import json
import os
from pathlib import Path

import FreeCAD as App

from hardware.lib.commun import boite_arrondie, matrice, piquet, texte

JSON = Path(__file__).resolve().parents[1] / "build" / "etiquettes.json"
MARGE = 3.0
MODULE_MIN = 0.8  # 2 lines of a 0.4 mm nozzle


def etiquette(p, code: str, qr: list[list[int]] | None):
    ep, relief, w = p.etiquette_ep, p.etiquette_relief, p.etiquette_w
    txt = texte(
        code, p.etiquette_texte_h, relief, p.police, MARGE, (w - p.etiquette_texte_h) / 2, ep
    )
    lg_txt = txt.BoundBox.XMax + MARGE
    cote_qr = w - 2 * MARGE if qr else 0.0
    lg = max(p.etiquette_l, lg_txt + (cote_qr + MARGE if qr else 0.0))
    s = boite_arrondie(lg, w, ep, 2, lg / 2, w / 2).fuse(txt)
    if qr:
        module = cote_qr / len(qr)
        if module < MODULE_MIN:
            App.Console.PrintWarning(
                f"label {code}: QR module {module:.2f} mm < {MODULE_MIN} mm (shorter --url)\n"
            )
        s = s.fuse(matrice(qr, module, relief, lg - MARGE - cote_qr, MARGE, ep))
    s = s.fuse(piquet(6, p.etiquette_piquet_l, ep, lg / 2, 2))
    return s.removeSplitter()


def pieces(p):
    chemin = Path(os.environ.get("SERREIA_ETIQUETTES", JSON))
    labels = json.loads(chemin.read_text()) if chemin.exists() else [{"id": "z1-A1", "qr": None}]
    return {f"etiquette_{lab['id']}": etiquette(p, lab["id"], lab["qr"]) for lab in labels}
