"""Pseudo-labels for the detector: Grad-CAM or YOLO v0, then SAM 2 (docs/04 §2).

    # CCMT / PlantVillage: Grad-CAM maps of `gradcam --save-cams`, peaks -> SAM 2 points
    python -m vision.labeling.pseudo_labels cams reports/<run>/cams_test_ccmt_sante.npz \
        --out labeling/ccmt_tasks.json
    # Greenhouse images: boxes of a first detector, refined by SAM 2
    python -m vision.labeling.pseudo_labels detector --detector runs/<id>/best.pt \
        --images data/serre/a_annoter --out labeling/serre_tasks.json

Steps: prompts -> SAM 2 mask -> box -> filters (area, score) -> NMS -> Label Studio tasks
(label_studio.to_tasks), to be corrected by hand then exported to YOLO.
"""

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from vision.datasets.build_index import DATA_DIR, IMAGE_EXTS
from vision.datasets.dataset import read_rgb
from vision.labeling.label_studio import Prediction, write_tasks
from vision.labeling.yolo_format import CLASSES, mask_to_box, nms

log = logging.getLogger(__name__)

SAM2_MODEL = "facebook/sam2.1-hiera-small"


@dataclass
class Filters:
    min_area: float = 0.005  # box area / image area
    max_area: float = 0.95  # larger boxes are usually the whole image (background mask)
    min_score: float = 0.5
    nms_iou: float = 0.7


class Segmenter(Protocol):
    """Promptable segmenter: one image, then masks from a point or a box."""

    def set_image(self, img: np.ndarray) -> None: ...

    def from_point(self, xy: tuple[float, float]) -> tuple[np.ndarray, float]: ...

    def from_box(self, box: tuple[float, float, float, float]) -> tuple[np.ndarray, float]: ...


class Sam2Segmenter:
    """SAM 2 (`pip install sam2`), weights from the Hugging Face hub on first use."""

    def __init__(self, model_id: str = SAM2_MODEL, device: str | None = None):
        import torch
        from sam2.sam2_image_predictor import SAM2ImagePredictor

        device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.predictor = SAM2ImagePredictor.from_pretrained(model_id, device=device)

    def set_image(self, img: np.ndarray) -> None:
        self.predictor.set_image(img)

    def from_point(self, xy):
        masks, scores, _ = self.predictor.predict(
            point_coords=np.array([xy], np.float32),
            point_labels=np.array([1]),
            multimask_output=True,  # ambiguous point: lesion, leaf or plant; keep the best
        )
        i = int(np.argmax(scores))
        return masks[i] > 0, float(scores[i])

    def from_box(self, box):
        masks, scores, _ = self.predictor.predict(
            box=np.array(box, np.float32), multimask_output=False
        )
        return masks[0] > 0, float(scores[0])


def cam_peaks(cam: np.ndarray, k: int = 3, min_dist: float = 0.15, thresh: float = 0.5):
    """Up to k local maxima (x, y) of a [0, 1] map, >= thresh, at least min_dist·size apart."""
    cam = cam.astype(np.float32)  # same dtype as the dilation, for the equality test
    size = max(cam.shape)
    r = max(1, round(min_dist * size / 2))
    dilated = cv2.dilate(cam, np.ones((2 * r + 1, 2 * r + 1), np.uint8))
    ys, xs = np.nonzero((cam >= dilated) & (cam >= thresh))
    order = np.argsort(-cam[ys, xs])
    peaks: list[tuple[float, float]] = []
    for i in order:
        p = (float(xs[i]), float(ys[i]))
        if all(np.hypot(p[0] - q[0], p[1] - q[1]) >= min_dist * size for q in peaks):
            peaks.append(p)
            if len(peaks) == k:
                break
    return np.array(peaks, np.float32).reshape(-1, 2)


def refine(
    seg: Segmenter,
    img: np.ndarray,
    points: np.ndarray | None = None,
    boxes: np.ndarray | None = None,
    prior: np.ndarray | None = None,
    filters: Filters | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """(boxes (n, 4), scores (n,)) from SAM masks prompted by points and/or boxes.

    prior: confidence of each box prompt (detector), multiplied with the SAM score.
    """
    filters = filters or Filters()
    h, w = img.shape[:2]
    seg.set_image(img)
    prompts = [("point", p, 1.0) for p in (points if points is not None else [])]
    if boxes is not None:
        prior = np.ones(len(boxes)) if prior is None else prior
        prompts += [("box", b, float(c)) for b, c in zip(boxes, prior, strict=True)]
    out_boxes, out_scores = [], []
    for kind, prompt, conf in prompts:
        fn = seg.from_point if kind == "point" else seg.from_box
        mask, score = fn(tuple(float(v) for v in prompt))
        box = mask_to_box(mask)
        score *= conf
        if box is None or score < filters.min_score:
            continue
        area = (box[2] - box[0]) * (box[3] - box[1]) / (w * h)
        if filters.min_area <= area <= filters.max_area:
            out_boxes.append(box)
            out_scores.append(score)
    if not out_boxes:
        return np.zeros((0, 4)), np.zeros(0)
    b, s = np.array(out_boxes), np.array(out_scores)
    keep = nms(b, s, filters.nms_iou)
    return b[keep], s[keep]


def ls_url(path: Path, root: Path) -> str:
    """Label Studio local-files URL (LOCAL_FILES_DOCUMENT_ROOT = root)."""
    return f"/data/local-files/?d={path.resolve().relative_to(root.resolve()).as_posix()}"


def from_cams(
    npz: Path, seg: Segmenter, data_dir: Path, ls_root: Path, k: int, thresh: float,
    filters: Filters,
) -> list[Prediction]:  # fmt: skip
    """Pseudo-labels from `gradcam --save-cams` maps (paths relative to data/)."""
    data = np.load(npz)
    preds = []
    for rel, cam in zip(data["paths"], data["cams"], strict=True):
        path = data_dir / str(rel)
        img = read_rgb(path)
        h, w = img.shape[:2]
        cam = cv2.resize(cam.astype(np.float32), (w, h))  # eval transform: plain resize
        boxes, scores = refine(seg, img, points=cam_peaks(cam, k, thresh=thresh), filters=filters)
        preds.append(_prediction(path, ls_root, w, h, boxes, scores))
    return preds


def from_detector(
    detector: Path, images: list[Path], seg: Segmenter, ls_root: Path, conf: float,
    filters: Filters,
) -> list[Prediction]:  # fmt: skip
    """Pseudo-labels from a first YOLO detector, each box refined by SAM 2."""
    from ultralytics import YOLO

    model = YOLO(str(detector))
    preds = []
    for path in images:
        img = read_rgb(path)
        h, w = img.shape[:2]
        det = model.predict(img[..., ::-1], conf=conf, verbose=False)[0].boxes  # BGR input
        boxes, scores = refine(
            seg, img, boxes=det.xyxy.cpu().numpy(), prior=det.conf.cpu().numpy(), filters=filters
        )
        preds.append(_prediction(path, ls_root, w, h, boxes, scores))
    return preds


def _prediction(path, ls_root, w, h, boxes, scores) -> Prediction:
    return Prediction(
        image=ls_url(path, ls_root),
        width=w,
        height=h,
        boxes=[tuple(map(float, b)) for b in boxes],
        labels=[CLASSES[0]] * len(boxes),
        scores=[float(s) for s in scores],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="mode", required=True)
    p_cams = sub.add_parser("cams", help="cartes Grad-CAM (.npz de gradcam --save-cams)")
    p_cams.add_argument("npz", type=Path, nargs="+")
    p_cams.add_argument("--k", type=int, default=3, help="pics par carte")
    p_cams.add_argument("--thresh", type=float, default=0.5, help="activation minimale d'un pic")
    p_det = sub.add_parser("detector", help="boîtes d'un premier détecteur YOLO")
    p_det.add_argument("--detector", type=Path, required=True)
    p_det.add_argument("--images", type=Path, required=True, help="dossier d'images")
    p_det.add_argument("--conf", type=float, default=0.25)
    for p in (p_cams, p_det):
        p.add_argument("--out", type=Path, required=True, help="tâches Label Studio (.json)")
        p.add_argument("--data-dir", type=Path, default=DATA_DIR)
        p.add_argument("--ls-root", type=Path, default=None,
                       help="LOCAL_FILES_DOCUMENT_ROOT (défaut : data-dir)")  # fmt: skip
        p.add_argument("--sam-model", default=SAM2_MODEL)
        p.add_argument("--device", default=None)
        p.add_argument("--min-area", type=float, default=Filters.min_area)
        p.add_argument("--min-score", type=float, default=Filters.min_score)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    filters = Filters(min_area=args.min_area, min_score=args.min_score)
    seg = Sam2Segmenter(args.sam_model, args.device)
    ls_root = args.ls_root or args.data_dir
    if args.mode == "cams":
        preds = []
        for npz in args.npz:
            preds += from_cams(npz, seg, args.data_dir, ls_root, args.k, args.thresh, filters)
    else:
        images = sorted(p for p in args.images.rglob("*") if p.suffix.lower() in IMAGE_EXTS)
        preds = from_detector(args.detector, images, seg, ls_root, args.conf, filters)
    write_tasks(preds, args.out, model_version=f"{args.mode}+sam2")
    n_boxes = sum(len(p.boxes) for p in preds)
    log.info("%d images, %d boîtes -> %s", len(preds), n_boxes, args.out)


if __name__ == "__main__":
    main()
