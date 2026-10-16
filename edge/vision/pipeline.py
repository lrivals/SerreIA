"""Inference of one capture (docs/05 §3 step 4): YOLO -> crops -> classifier -> PatchCore ->
growth indicators, as a contract VisionResult plus the extras kept in the archive.

Without a detector, or when it finds no leaf, every plant ROI (or the whole image) is
classified as one detection, as in phase 1: `bbox` is the ROI, or null for the whole image.
"""

import math
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from common.mqtt import Detection, VisionResult
from vision.growth.canopy import CanopySegmenter, ExgOtsu, measure
from vision.labeling.yolo_format import crop

from .preprocess import Roi

Detector = Callable[[np.ndarray], tuple[np.ndarray, np.ndarray]]
Classifier = Callable[[Sequence[np.ndarray]], list[dict]]
AnomalyScorer = Callable[[Sequence[np.ndarray], str], float | None]  # images, espece -> [0, 1]


@dataclass(frozen=True)
class Plant:
    id: str
    roi: Roi | None = None
    px_per_cm: float | None = None
    base_row: int | None = None


def image_id(camera: str, ts: datetime) -> str:
    return f"{camera}-{ts:%Y%m%dT%H%M%S}"


def norm_bbox(box, shape) -> tuple[float, float, float, float]:
    """Pixel xyxy -> (x, y, w, h) normalized to [0, 1] (contract)."""
    h, w = shape[:2]
    x0, y0, x1, y1 = (float(v) for v in box)
    x0, x1 = min(max(x0 / w, 0.0), 1.0), min(max(x1 / w, 0.0), 1.0)
    y0, y1 = min(max(y0 / h, 0.0), 1.0), min(max(y1 / h, 0.0), 1.0)
    return x0, y0, x1 - x0, y1 - y0


def _clean(d: dict) -> dict:
    """NaN -> None: the archive JSON must stay strict JSON."""
    return {k: None if isinstance(v, float) and math.isnan(v) else v for k, v in d.items()}


class PatchCoreScorer:
    """PatchCore per species (vision.anomaly.patchcore, torch), loaded on first use.

    Raw score s mapped to [0, 1] by min(1, s / (2 * threshold)): the calibrated threshold
    lands on 0.5. Species without a memory bank: None (not scored).
    """

    def __init__(self, paths: dict[str, Path], device: str = "cpu"):
        self.paths, self.device, self.models = paths, device, {}

    def __call__(self, images: Sequence[np.ndarray], espece: str) -> float | None:
        if espece not in self.paths:
            return None
        if espece not in self.models:
            from vision.anomaly.patchcore import PatchCore

            self.models[espece] = PatchCore.load(self.paths[espece], self.device)
        model = self.models[espece]
        scores, _ = model.score(list(images))
        return float(min(1.0, scores.max() / (2 * model.threshold)))


class EdgePipeline:
    def __init__(
        self,
        classifier: Classifier,
        modele: str,
        detector: Detector | None = None,
        anomaly: AnomalyScorer | None = None,
        segmenter: CanopySegmenter | None = None,
        margin: float = 0.1,
    ):
        self.classifier, self.modele, self.detector = classifier, modele, detector
        self.anomaly, self.margin = anomaly, margin
        self.segmenter = segmenter or ExgOtsu()

    def regions(self, img: np.ndarray, plants: Sequence[Plant]) -> list[tuple]:
        """(crop, normalized bbox or None) to classify."""
        if self.detector is not None:
            boxes, _ = self.detector(img)
            if len(boxes):
                return [(crop(img, b, self.margin), norm_bbox(b, img.shape)) for b in boxes]
        rois = [p.roi for p in plants if p.roi is not None]
        if rois:
            return [(crop(img, r, 0.0), norm_bbox(r, img.shape)) for r in rois]
        return [(img, None)]

    def __call__(
        self, img: np.ndarray, camera: str, ts: datetime, plants: Sequence[Plant] = ()
    ) -> tuple[VisionResult, dict]:
        regions = self.regions(img, plants)
        heads = self.classifier([c for c, _ in regions])
        detections = [
            Detection(bbox=bbox, **{k: r[k] for k in Detection.model_fields if k != "bbox"})
            for (_, bbox), r in zip(regions, heads, strict=True)
        ]

        # Anomaly: PatchCore of the majority species, on the plant ROIs (or whole image).
        espece = Counter(r["espece"] for r in heads).most_common(1)[0][0]
        anomaly = None
        if self.anomaly is not None:
            views = [crop(img, p.roi, 0.0) for p in plants if p.roi is not None] or [img]
            anomaly = self.anomaly(views, espece)

        growth = {}
        for p in plants or [Plant("image")]:
            ind = measure(
                img, self.segmenter, roi=p.roi, px_per_cm=p.px_per_cm, base_row=p.base_row
            )
            growth[p.id] = _clean(ind.as_dict())

        result = VisionResult(
            ts=ts,
            camera=camera,
            image_id=image_id(camera, ts),
            modele=self.modele,
            detections=detections,
            score_anomalie=anomaly or 0.0,
            surface_verte_px=sum(g["surface_px"] for g in growth.values()),
        )
        extras = {
            "classifieur": heads,
            "espece_majoritaire": espece,
            "anomalie_evaluee": anomaly is not None,
            "croissance": growth,
            "taille_image": list(img.shape[:2]),
        }
        return result, extras
