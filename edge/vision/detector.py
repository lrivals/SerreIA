"""YOLO leaf detector on the edge (docs/04 §1, docs/05 §2): ONNX (PC) or HEF with on-chip NMS.

Same signature as vision.eval.two_stage.Detector: RGB image -> (boxes (k, 4) pixel xyxy,
confidences (k,)), class `feuille` only.
"""

from typing import Any

import cv2
import numpy as np

from vision.labeling.yolo_format import nms

from .backends import Backend

PAD_VALUE = 114  # Ultralytics letterbox grey


def letterbox(
    img: np.ndarray, size: tuple[int, int]
) -> tuple[np.ndarray, float, tuple[float, float]]:
    """Resize keeping the aspect ratio, pad (centered) to size (H, W).

    Returns the image, the scale and the (x, y) padding, to map boxes back.
    """
    h, w = img.shape[:2]
    r = min(size[0] / h, size[1] / w)
    nw, nh = round(w * r), round(h * r)
    px, py = (size[1] - nw) / 2, (size[0] - nh) / 2
    out = np.full((size[0], size[1], 3), PAD_VALUE, np.uint8)
    top, left = round(py - 0.1), round(px - 0.1)
    out[top : top + nh, left : left + nw] = cv2.resize(
        img, (nw, nh), interpolation=cv2.INTER_LINEAR
    )
    return out, r, (left, top)


def unletterbox(boxes: np.ndarray, r: float, pad: tuple[float, float], shape) -> np.ndarray:
    """Boxes of the letterboxed input (pixels) -> boxes of the original image, clipped."""
    b = np.asarray(boxes, np.float32).reshape(-1, 4).copy()
    b[:, [0, 2]] = (b[:, [0, 2]] - pad[0]) / r
    b[:, [1, 3]] = (b[:, [1, 3]] - pad[1]) / r
    b[:, [0, 2]] = b[:, [0, 2]].clip(0, shape[1])
    b[:, [1, 3]] = b[:, [1, 3]].clip(0, shape[0])
    return b


def decode_yolov8(
    raw: np.ndarray, conf: float, keep_class: int, iou: float
) -> tuple[np.ndarray, np.ndarray]:
    """Ultralytics head output (4 + nc, anchors) -> (boxes xyxy, conf) of keep_class after NMS."""
    pred = np.asarray(raw, np.float32).T  # (anchors, 4 + nc)
    scores = pred[:, 4:]
    cls = scores.argmax(1)
    best = scores[np.arange(len(pred)), cls]
    sel = (cls == keep_class) & (best >= conf)
    cx, cy, w, h = pred[sel, :4].T
    boxes = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], 1)
    keep = nms(boxes, best[sel], iou) if len(boxes) else np.zeros(0, int)
    return boxes[keep], best[sel][keep]


def parse_hailo_nms(
    per_class: Any, size: tuple[int, int], conf: float, keep_class: int
) -> tuple[np.ndarray, np.ndarray]:
    """On-chip NMS output of one image: per-class (k, 5) arrays [ymin, xmin, ymax, xmax, score]
    normalized to the input -> (boxes xyxy in input pixels, conf)."""
    dets = np.asarray(per_class[keep_class], np.float32).reshape(-1, 5)
    dets = dets[dets[:, 4] >= conf]
    h, w = size
    boxes = np.stack([dets[:, 1] * w, dets[:, 0] * h, dets[:, 3] * w, dets[:, 2] * h], 1)
    return boxes, dets[:, 4]


class EdgeYolo:
    """YOLOv8 on a Backend. `nms_on_chip`: HEF compiled from the Model Zoo configuration."""

    def __init__(self, backend: Backend, conf: float = 0.25, iou: float = 0.7, keep_class: int = 0,
                 nms_on_chip: bool = False):  # fmt: skip
        self.backend, self.conf, self.iou = backend, conf, iou
        self.keep_class, self.nms_on_chip = keep_class, nms_on_chip

    def __call__(self, img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        x, r, pad = letterbox(img, self.backend.input_size)
        out = self.backend(x[None])[0][0]
        if self.nms_on_chip:
            boxes, conf = parse_hailo_nms(out, self.backend.input_size, self.conf, self.keep_class)
        else:
            boxes, conf = decode_yolov8(out, self.conf, self.keep_class, self.iou)
        return unletterbox(boxes, r, pad, img.shape), conf
