"""INT8 calibration set of the Hailo Dataflow Compiler (docs/05 §2).

python -m vision.export.calibration --model clf --n 1024 [--size 224]
python -m vision.export.calibration --model yolo --n 512 [--size 640]

512 to 1,024 representative images: greenhouse images first (`data/serre/`, as soon as
there are some), completed by a class-stratified sample of the `val` splits. Saved as
`runs/export/calib_<model>_<size>.npy`, (N, S, S, 3) uint8 RGB: the DFC `optimize` takes
NHWC, and the normalization is in the model script (hailo/clf.alls). The images are
prepared exactly as on the edge: plain resize for the classifier, letterbox for YOLO.
"""

import argparse
import logging
import shutil
from collections.abc import Sequence
from pathlib import Path

import cv2
import numpy as np

from edge.vision.detector import letterbox
from vision.datasets.build_index import DATA_DIR, IMAGE_EXTS, INDEX_NAME
from vision.datasets.dataset import load_index, read_rgb, stratified_subset

log = logging.getLogger(__name__)

EXPORT_DIR = Path(__file__).resolve().parents[2] / "runs" / "export"


def list_images(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(p for p in folder.rglob("*") if p.suffix.lower() in IMAGE_EXTS)


def calibration_paths(
    n: int, data_dir: Path = DATA_DIR, serre_dir: Path | None = None, seed: int = 0
) -> list[Path]:
    """Greenhouse images first (at most n), completed by the val splits of the index."""
    rng = np.random.default_rng(seed)
    serre = list_images(serre_dir if serre_dir is not None else data_dir / "serre")
    if len(serre) > n:
        serre = [serre[i] for i in sorted(rng.choice(len(serre), n, replace=False))]
    paths = list(serre)
    missing = n - len(paths)
    index = data_dir / INDEX_NAME
    if missing > 0 and index.exists():
        df = stratified_subset(load_index(index, ["val"]), missing, seed)
        paths += [data_dir / p for p in df["path"].head(missing)]
    log.info(
        "calibration : %d images de serre, %d du split val", len(serre), len(paths) - len(serre)
    )
    return paths


def prepare(img: np.ndarray, size: int, mode: str) -> np.ndarray:
    if mode == "yolo":
        return letterbox(img, (size, size))[0]
    return cv2.resize(img, (size, size), interpolation=cv2.INTER_LINEAR)


def build_calibration(paths: Sequence[Path], size: int, mode: str = "clf") -> np.ndarray:
    """(N, size, size, 3) uint8 RGB; unreadable images are skipped."""
    out = []
    for p in paths:
        try:
            out.append(prepare(read_rgb(p), size, mode))
        except OSError as e:
            log.warning("%s", e)
    if not out:
        raise ValueError("aucune image de calibration lisible")
    return np.stack(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", choices=["clf", "yolo"], default="clf")
    parser.add_argument("--n", type=int, default=1024)
    parser.add_argument("--size", type=int, default=None, help="défaut : 224 (clf), 640 (yolo)")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--serre-dir", type=Path, default=None, help="défaut : <data>/serre")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--images-out", type=Path, default=None,
                        help="copie aussi les images brutes (hailomz --calib-path)")  # fmt: skip
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    size = args.size or (640 if args.model == "yolo" else 224)
    if not 512 <= args.n <= 1024:
        log.warning("docs/05 §2 recommande 512 à 1 024 images (n = %d)", args.n)
    paths = calibration_paths(args.n, args.data_dir, args.serre_dir)
    if args.images_out:
        args.images_out.mkdir(parents=True, exist_ok=True)
        for i, p in enumerate(paths):
            shutil.copy(p, args.images_out / f"{i:05d}{p.suffix.lower()}")
    calib = build_calibration(paths, size, args.model)
    out = args.out or EXPORT_DIR / f"calib_{args.model}_{size}.npy"
    out.parent.mkdir(parents=True, exist_ok=True)
    np.save(out, calib)
    print(f"{out} : {calib.shape} {calib.dtype}")


if __name__ == "__main__":
    main()
