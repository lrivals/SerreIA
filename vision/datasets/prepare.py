"""Reorganise raw downloads into the target layout of docs/02-donnees.md §1.

    python -m vision.datasets.prepare ccmt
    python -m vision.datasets.prepare plantdoc --src ~/Downloads/PlantDoc-Object-Detection-Dataset

Idempotent and non-destructive: folders are moved or copied, never deleted.
"""

import argparse
import glob
import logging
import re
import shutil
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from PIL import Image

from vision.datasets.taxonomy import load_taxonomy

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
CCMT_DOWNLOAD = "Dataset for Crop Pest and Disease Detection"
MIN_CROP = 32  # px, smaller boxes are unusable for the classifier

Box = tuple[str, tuple[float, float, float, float]]


def prepare_ccmt(data_dir: Path) -> None:
    src = data_dir / CCMT_DOWNLOAD
    dst = data_dir / "ccmt"
    moves = {
        src / "Raw Data" / "CCMT Dataset": dst / "raw",
        src / "CCMT Dataset-Augmented": dst / "augmented",
    }
    for a, b in moves.items():
        if b.exists():
            log.info("déjà en place : %s", b)
        elif a.exists():
            b.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(a, b)
            log.info("déplacé : %s -> %s", a, b)
        else:
            log.warning("introuvable : %s", a)
    # Remove the now-empty download shell, deepest folders first; anything non-empty stays.
    if src.exists():
        for d in sorted((p for p in src.rglob("*") if p.is_dir()), reverse=True) + [src]:
            if not any(d.iterdir()):
                d.rmdir()


def _find_split_dir(src: Path, name: str) -> Path:
    for d in src.rglob("*"):
        if d.is_dir() and d.name.lower() == name:
            return d
    raise FileNotFoundError(f"dossier {name.upper()}/ introuvable sous {src}")


def _parse_voc(xml_path: Path) -> tuple[tuple[int, int] | None, list[Box]]:
    """Annotated (width, height) and boxes of a VOC file."""
    root = ET.parse(xml_path).getroot()
    size = None
    if (w := root.findtext("size/width")) and (h := root.findtext("size/height")):
        size = (int(float(w)), int(float(h)))
    boxes = []
    for obj in root.iter("object"):
        bb = obj.find("bndbox")
        name = " ".join(obj.findtext("name", "").split())
        if bb is None or not name:
            continue
        coords = [float(bb.findtext(k)) for k in ("xmin", "ymin", "xmax", "ymax")]
        boxes.append((name, tuple(coords)))
    return size, boxes


def _image_for(xml_path: Path) -> Path | None:
    """Image sharing the XML stem; PlantDoc names are raw URLs (`a.jpeg?itok=x.jpg`)."""
    for p in sorted(xml_path.parent.glob(glob.escape(xml_path.stem) + ".*")):
        if p != xml_path and p.suffix.lower() != ".xml":
            return p
    return None


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120]


def extract_crops(split_dir: Path, crops_dir: Path) -> Counter:
    """Crop every VOC box of split_dir into crops_dir/<label>/<stem>_<i>.jpg."""
    labels: Counter = Counter()
    for xml_path in sorted(split_dir.glob("*.xml")):
        img_path = _image_for(xml_path)
        if img_path is None:
            log.warning("image manquante : %s", xml_path.name)
            continue
        try:
            size, boxes = _parse_voc(xml_path)
            img = Image.open(img_path).convert("RGB")
        except (ET.ParseError, OSError, TypeError, ValueError) as e:
            log.warning("ignoré %s : %s", img_path.name, e)
            continue
        w, h = img.size
        # Some PlantDoc boxes were drawn on a resized copy of the image.
        sx, sy = (w / size[0], h / size[1]) if size and all(size) else (1.0, 1.0)
        stem = _safe_name(xml_path.stem)
        for i, (label, (x0, y0, x1, y1)) in enumerate(boxes):
            x0, x1 = max(0, round(x0 * sx)), min(w, round(x1 * sx))
            y0, y1 = max(0, round(y0 * sy)), min(h, round(y1 * sy))
            if x1 - x0 < MIN_CROP or y1 - y0 < MIN_CROP:
                continue
            out = crops_dir / label / f"{stem}_{i}.jpg"
            if not out.exists():
                out.parent.mkdir(parents=True, exist_ok=True)
                img.crop((x0, y0, x1, y1)).save(out, quality=95)
            labels[label] += 1
    return labels


def prepare_plantdoc(data_dir: Path, src: Path | None) -> None:
    dst = data_dir / "plantdoc"
    for split in ("train", "test"):
        target = dst / split
        if not target.exists():
            if src is None:
                raise SystemExit(f"{target} absent : préciser --src")
            shutil.copytree(_find_split_dir(src, split), target)
            log.info("copié : %s", target)

    taxo = load_taxonomy()
    labels: Counter = Counter()
    for split in ("train", "test"):
        labels += extract_crops(dst / split, dst / "crops" / split)
    print(f"\nPlantDoc : {sum(labels.values())} crops, {len(labels)} labels")
    for label, n in sorted(labels.items()):
        mark = "  " if taxo.has("plantdoc", label) else "!!"
        print(f"  {mark} {label:45s} {n}")
    missing = [lbl for lbl in labels if not taxo.has("plantdoc", lbl)]
    if missing:
        print(f"\n{len(missing)} label(s) non mappé(s) (!!) : compléter taxonomy.yaml.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dataset", choices=["ccmt", "plantdoc"])
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--src", type=Path, help="téléchargement PlantDoc (contient TRAIN/ TEST/)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.dataset == "ccmt":
        prepare_ccmt(args.data_dir)
    else:
        prepare_plantdoc(args.data_dir, args.src)


if __name__ == "__main__":
    main()
