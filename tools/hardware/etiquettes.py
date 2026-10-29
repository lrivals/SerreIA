"""Labels of the emplacements (docs/20 §4 E), generated from the greenhouse configuration.

    python -m tools.hardware.etiquettes                          # or: make etiquettes
    python -m tools.hardware.etiquettes --config serre.yaml --url https://serre.local/e/

Writes `hardware/build/etiquettes.json`: one label per emplacement (id, zone, plant) with
the matrix of its QR code, read by `hardware/pieces/etiquette.py` in FreeCAD. The QR code
holds `<url><emplacement id>` (the id alone by default: the UI has no page per emplacement
yet). Without `segno` (extra `hardware`), the labels have no QR code.
"""

import argparse
import json
from pathlib import Path

from edge.controller.config import DEFAULT_CONFIG, load_greenhouse

ROOT = Path(__file__).resolve().parents[2]
SORTIE = ROOT / "hardware" / "build" / "etiquettes.json"


def qr_matrice(texte: str) -> list[list[int]] | None:
    """Modules of the QR code of `texte` (1 = dark, no quiet zone); None without segno."""
    try:
        import segno
    except ImportError:
        return None
    qr = segno.make_qr(texte, error="m")
    return [[int(b) for b in ligne] for ligne in qr.matrix]


def etiquettes(config: Path = DEFAULT_CONFIG, url: str = "") -> list[dict]:
    cfg = load_greenhouse(config).cfg
    return [
        {
            "id": e.id,
            "zone": z.id,
            "plante": e.plante.id if e.plante else None,
            "qr": qr_matrice(url + e.id),
        }
        for z in cfg.zones
        for e in z.emplacements
    ]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--url", default="", help="prefix of the QR content")
    ap.add_argument("--out", type=Path, default=SORTIE)
    args = ap.parse_args(argv)
    labels = etiquettes(args.config, args.url)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(labels, ensure_ascii=False))
    sans_qr = sum(lab["qr"] is None for lab in labels)
    print(
        f"{len(labels)} labels -> {args.out}"
        + (f" ({sans_qr} without QR: pip install segno)" if sans_qr else "")
    )


if __name__ == "__main__":
    main()
