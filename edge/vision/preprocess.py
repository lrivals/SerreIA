"""Capture pre-processing (docs/05 §3 step 3): white balance on a fixed grey card, resizing."""

import cv2
import numpy as np

Roi = tuple[int, int, int, int]  # x0, y0, x1, y1 in pixels


def gray_card_wb(img: np.ndarray, roi: Roi, max_gain: float = 3.0) -> np.ndarray:
    """Per-channel gains that make the grey card neutral, keeping its mean luminance.

    Under coloured horticultural LEDs this removes most of the cast before inference.
    """
    x0, y0, x1, y1 = roi
    patch = img[y0:y1, x0:x1].reshape(-1, 3).astype(np.float32)
    if patch.size == 0:
        raise ValueError(f"ROI de mire vide : {roi}")
    means = patch.mean(0)
    gains = np.clip(means.mean() / np.maximum(means, 1.0), 1 / max_gain, max_gain)
    return np.clip(img.astype(np.float32) * gains, 0, 255).astype(np.uint8)


def resize_max(img: np.ndarray, side: int) -> tuple[np.ndarray, float]:
    """Downscale so that the longest side is at most `side`; returns the image and the scale."""
    h, w = img.shape[:2]
    s = side / max(h, w)
    if s >= 1:
        return img, 1.0
    return cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA), s
