"""YOLO dataset format (docs/04-detection-yolo.md §2): `labels/*.txt` and `data.yaml`.

One line per box: `<class> <x_center> <y_center> <width> <height>`, coordinates normalized
to [0, 1] by the image size.
"""

from collections.abc import Iterable, Sequence
from pathlib import Path

import numpy as np
import yaml

CLASSES = ("feuille", "plante", "fruit")  # generic detector classes (§1)
SPLITS = ("train", "val", "test")

PixelBox = tuple[float, float, float, float]  # x0, y0, x1, y1 in pixels
YoloBox = tuple[int, float, float, float, float]  # class, xc, yc, w, h normalized


def to_yolo(cls: int, box: PixelBox, w: int, h: int) -> YoloBox:
    x0, y0, x1, y1 = box
    return cls, (x0 + x1) / 2 / w, (y0 + y1) / 2 / h, (x1 - x0) / w, (y1 - y0) / h


def from_yolo(box: YoloBox, w: int, h: int) -> tuple[int, PixelBox]:
    cls, xc, yc, bw, bh = box
    return cls, ((xc - bw / 2) * w, (yc - bh / 2) * h, (xc + bw / 2) * w, (yc + bh / 2) * h)


def mask_to_box(mask: np.ndarray) -> PixelBox | None:
    """Bounding box (x1, y1 exclusive) of the non-zero pixels; None if the mask is empty."""
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    return float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1)


def write_labels(path: Path, boxes: Iterable[YoloBox]) -> None:
    """An empty file is a valid background image (no object)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{c} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}" for c, xc, yc, w, h in boxes]
    path.write_text("".join(line + "\n" for line in lines))


def read_labels(path: Path) -> list[YoloBox]:
    out = []
    for line in path.read_text().splitlines():
        if line.strip():
            c, *coords = line.split()
            out.append((int(c), *map(float, coords)))
    return out


def label_path(image_path: Path) -> Path:
    """Ultralytics convention: the last `images` folder of the path becomes `labels`."""
    parts = list(image_path.parts)
    i = len(parts) - 1 - parts[::-1].index("images")
    parts[i] = "labels"
    return Path(*parts).with_suffix(".txt")


def write_data_yaml(root: Path, classes: Sequence[str] = CLASSES, splits=SPLITS) -> Path:
    """data.yaml without `path`: Ultralytics then uses the file's folder (portable tar)."""
    cfg: dict = {s: f"images/{s}" for s in splits}
    cfg["names"] = dict(enumerate(classes))
    out = root / "data.yaml"
    out.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return out


def box_iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """(n, m) IoU between pixel boxes a (n, 4) and b (m, 4), x0 y0 x1 y1."""
    a, b = np.asarray(a, float).reshape(-1, 4), np.asarray(b, float).reshape(-1, 4)
    lt = np.maximum(a[:, None, :2], b[None, :, :2])
    rb = np.minimum(a[:, None, 2:], b[None, :, 2:])
    inter = np.clip(rb - lt, 0, None).prod(-1)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    union = area_a[:, None] + area_b[None, :] - inter
    return np.where(union > 0, inter / np.maximum(union, 1e-9), 0.0)


def nms(boxes: np.ndarray, scores: np.ndarray, iou: float = 0.7) -> np.ndarray:
    """Indices kept by greedy non-maximum suppression, best score first."""
    order = np.argsort(-np.asarray(scores, float))
    keep: list[int] = []
    for i in order:
        if not keep or box_iou(boxes[i], boxes[keep]).max() < iou:
            keep.append(int(i))
    return np.array(keep, dtype=int)


def crop(img: np.ndarray, box: PixelBox, margin: float) -> np.ndarray:
    """Box enlarged by margin (fraction of its size) on each side, clipped to the image."""
    h, w = img.shape[:2]
    x0, y0, x1, y1 = box
    mx, my = margin * (x1 - x0), margin * (y1 - y0)
    x0, y0 = int(max(0, x0 - mx)), int(max(0, y0 - my))
    x1, y1 = int(min(w, x1 + mx)), int(min(h, y1 + my))
    return img[y0 : max(y1, y0 + 1), x0 : max(x1, x0 + 1)]
