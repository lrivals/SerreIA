"""Canopy segmentation and growth indicators of one capture (docs/04 §5, steps 1 and 2).

First version: excess-green index ExG = 2g − r − b on chromatic coordinates (r = R / (R+G+B)…)
thresholded by Otsu. A light segmentation model (YOLOv8n-seg) can replace it later behind the
same `CanopySegmenter` interface. Strongly yellowed leaves have a low ExG and may drop out
of the mask: the yellowing index is then an underestimate, the green area falls anyway.
"""

from dataclasses import asdict, dataclass
from typing import Protocol

import cv2
import numpy as np

# OpenCV hue (0-179): yellow 20-34, green 35-90 (≈ 40-68° and 70-180°).
YELLOW_HUE = (20, 35)
GREEN_HUE = (35, 90)


class CanopySegmenter(Protocol):
    def __call__(self, img: np.ndarray) -> np.ndarray:
        """RGB uint8 image -> {0, 1} uint8 mask of the vegetation."""
        ...


def exg(img: np.ndarray) -> np.ndarray:
    """Excess-green index in [-1, 2] of an RGB image."""
    x = img.astype(np.float32)
    s = x.sum(2) + 1e-6
    r, g, b = x[..., 0] / s, x[..., 1] / s, x[..., 2] / s
    return 2 * g - r - b


class ExgOtsu:
    """ExG + Otsu threshold, small specks removed by a morphological opening."""

    def __init__(self, min_exg: float = 0.05, open_px: int = 3):
        self.min_exg, self.open_px = min_exg, open_px

    def __call__(self, img: np.ndarray) -> np.ndarray:
        e = exg(img)
        u8 = np.clip((e + 1) / 3 * 255, 0, 255).astype(np.uint8)
        t, _ = cv2.threshold(u8, 0, 1, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        # Otsu always splits: on an image without plants, keep only clearly green pixels.
        mask = ((u8 > t) & (e > self.min_exg)).astype(np.uint8)
        if self.open_px > 1:
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (self.open_px, self.open_px))
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
        return mask


@dataclass
class Indicators:
    surface_px: int
    surface_cm2: float | None  # with a calibration chart (px_per_cm)
    hauteur_px: int | None  # side camera: base_row - top row of the canopy
    hauteur_cm: float | None
    teinte_moy: float  # mean hue of the canopy, degrees (0-360)
    jaunissement: float  # yellow pixels / (yellow + green) pixels of the canopy

    def as_dict(self) -> dict:
        return asdict(self)


def indicators(
    img: np.ndarray,
    mask: np.ndarray,
    px_per_cm: float | None = None,
    base_row: int | None = None,
) -> Indicators:
    """Indicators of a capture (or a plant ROI) and its canopy mask.

    px_per_cm: scale from the calibration chart; base_row: image row of the pot rim on a
    side camera (height measured upwards from it).
    """
    m = mask.astype(bool)
    surface = int(m.sum())
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    hue = hsv[..., 0][m].astype(np.float32)
    if surface:
        ang = np.deg2rad(hue * 2)  # circular mean: hue wraps around
        teinte = float(np.rad2deg(np.arctan2(np.sin(ang).mean(), np.cos(ang).mean())) % 360)
    else:
        teinte = float("nan")
    yellow = ((hue >= YELLOW_HUE[0]) & (hue < YELLOW_HUE[1])).sum()
    green = ((hue >= GREEN_HUE[0]) & (hue < GREEN_HUE[1])).sum()
    jaune = float(yellow / (yellow + green)) if yellow + green else float("nan")

    hauteur = None
    if base_row is not None and surface:
        top = int(np.flatnonzero(m.any(1))[0])
        hauteur = max(0, base_row - top)
    return Indicators(
        surface_px=surface,
        surface_cm2=surface / px_per_cm**2 if px_per_cm else None,
        hauteur_px=hauteur,
        hauteur_cm=hauteur / px_per_cm if px_per_cm and hauteur is not None else None,
        teinte_moy=teinte,
        jaunissement=jaune,
    )


def measure(
    img: np.ndarray,
    segmenter: CanopySegmenter | None = None,
    roi: tuple[int, int, int, int] | None = None,
    **kw,
) -> Indicators:
    """Segment then measure a capture, optionally restricted to a plant ROI (x0, y0, x1, y1)."""
    if roi is not None:
        x0, y0, x1, y1 = roi
        img = img[y0:y1, x0:x1]
        if kw.get("base_row") is not None:
            kw["base_row"] -= y0
    mask = (segmenter or ExgOtsu())(img)
    return indicators(img, mask, **kw)
