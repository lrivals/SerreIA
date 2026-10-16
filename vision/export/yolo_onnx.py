"""ONNX export of the YOLO leaf detector, checked against the Ultralytics model (docs/05 §2).

python -m vision.export.yolo_onnx --weights runs/<yolo_run>/best.pt [--images data/plantdoc/test]

Raw head output (1, 4 + nc, anchors), without NMS: the NMS runs on the edge in numpy
(edge.vision.detector), or on the chip once compiled from the Hailo Model Zoo config.
Check: share of the PyTorch leaves found again by the ONNX graph (IoU >= 0.9).
"""

import argparse
import logging
import shutil
from pathlib import Path

import numpy as np

from edge.vision.backends import OnnxBackend
from edge.vision.detector import EdgeYolo
from vision.datasets.build_index import IMAGE_EXTS
from vision.datasets.dataset import read_rgb
from vision.labeling.yolo_format import box_iou

log = logging.getLogger(__name__)

OPSET = 17
IOU_SAME = 0.9


def export_yolo(weights: Path, out: Path, imgsz: int = 640) -> dict:
    """ONNX at `out`; returns its manifest entry (edge/vision/bundle.py)."""
    from ultralytics import YOLO

    model = YOLO(str(weights))
    path = Path(model.export(format="onnx", opset=OPSET, imgsz=imgsz, simplify=True,
                             dynamic=False, nms=False))  # fmt: skip
    out.parent.mkdir(parents=True, exist_ok=True)
    if path.resolve() != out.resolve():
        shutil.move(path, out)
    return {
        "onnx": out.name,
        "imgsz": imgsz,
        "classes": [model.names[i] for i in sorted(model.names)],
    }


def compare_yolo(weights: Path, onnx_path: Path, images: list[Path], conf: float = 0.25) -> dict:
    from vision.eval.two_stage import YoloDetector

    ref = YoloDetector(weights, conf=conf, device="cpu")
    edge = EdgeYolo(OnnxBackend(onnx_path, "unit"), conf=conf)
    n_ref = n_found = n_onnx = 0
    for p in images:
        img = read_rgb(p)
        b_ref, _ = ref(img)
        b_onnx, _ = edge(img)
        n_ref, n_onnx = n_ref + len(b_ref), n_onnx + len(b_onnx)
        if len(b_ref) and len(b_onnx):
            n_found += int((box_iou(b_ref, b_onnx).max(1) >= IOU_SAME).sum())
    return {
        "images": len(images),
        "feuilles_pytorch": n_ref,
        "feuilles_onnx": n_onnx,
        "retrouvees": n_found / n_ref if n_ref else float("nan"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None, help="défaut : <run>/yolo.onnx")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--images", type=Path, default=None, help="dossier pour la vérification")
    parser.add_argument("--n", type=int, default=20)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    out = args.out or args.weights.parent / "yolo.onnx"
    entry = export_yolo(args.weights, out, args.imgsz)
    log.info("export : %s %s", out, entry)
    if args.images:
        paths = sorted(p for p in args.images.rglob("*") if p.suffix.lower() in IMAGE_EXTS)
        paths = [
            paths[i] for i in np.linspace(0, len(paths) - 1, min(args.n, len(paths))).astype(int)
        ]
        for k, v in compare_yolo(args.weights, out, paths).items():
            print(f"{k:18s} {v}")


if __name__ == "__main__":
    main()
