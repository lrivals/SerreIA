"""Growth tracking (docs/04-detection-yolo.md §5) on synthetic captures."""

import cv2
import numpy as np
import pytest

pytest.importorskip("scipy")

from vision.growth.canopy import ExgOtsu, exg, indicators, measure  # noqa: E402
from vision.growth.curve import fit_logistic, growth_alert, logistic  # noqa: E402

SOIL = (110, 90, 70)


def _scene(radius: int, color=(50, 150, 40), size: int = 200) -> np.ndarray:
    img = np.full((size, size, 3), SOIL, np.uint8)
    cv2.circle(img, (size // 2, size // 2), radius, color, -1)
    return img


def test_exg_green_positive():
    e = exg(_scene(30))
    assert e[100, 100] > 0.2 and e[5, 5] < 0.1


def test_canopy_area_and_scale():
    img = _scene(30)
    mask = ExgOtsu()(img)
    assert mask.sum() == pytest.approx(np.pi * 30**2, rel=0.05)
    ind = indicators(img, mask, px_per_cm=10)
    assert ind.surface_cm2 == pytest.approx(ind.surface_px / 100)
    assert 70 < ind.teinte_moy < 140  # green hue
    assert ind.jaunissement == pytest.approx(0.0, abs=0.01)


def test_empty_scene():
    mask = ExgOtsu()(np.full((50, 50, 3), SOIL, np.uint8))
    assert mask.sum() == 0
    ind = indicators(np.zeros((50, 50, 3), np.uint8), mask)
    assert ind.surface_px == 0 and ind.hauteur_px is None


def test_yellowing_index():
    img = _scene(40)
    cv2.circle(img, (100, 100), 20, (150, 160, 40), -1)  # yellowing centre, still greenish
    mask = np.zeros(img.shape[:2], np.uint8)
    cv2.circle(mask, (100, 100), 40, 1, -1)
    ind = indicators(img, mask)
    assert ind.jaunissement == pytest.approx(0.25, abs=0.05)


def test_height_side_camera_and_roi():
    img = np.full((120, 100, 3), SOIL, np.uint8)
    img[40:100, 45:55] = (50, 150, 40)  # stem from row 40 down to the pot rim (row 100)
    ind = measure(img, base_row=100, px_per_cm=4)
    assert ind.hauteur_px == 60 and ind.hauteur_cm == 15
    roi = measure(img, roi=(0, 20, 100, 120), base_row=100)
    assert roi.hauteur_px == 60


def test_fit_logistic_recovers_parameters():
    rng = np.random.default_rng(0)
    t = np.repeat(np.arange(0, 60, 2.0), 2)  # two cycles
    y = logistic(t, 800, 0.15, 30) + rng.normal(0, 10, len(t))
    curve = fit_logistic(t, y)
    assert curve.k == pytest.approx(800, rel=0.05)
    assert curve.r == pytest.approx(0.15, rel=0.15)
    assert curve.t0 == pytest.approx(30, abs=2)
    assert curve.sigma == pytest.approx(10, rel=0.3)
    with pytest.raises(ValueError):
        fit_logistic([1, 2, 3], [1, 2, 3])


def test_growth_alert_needs_n_consecutive():
    expected = np.full(10, 100.0)
    obs = expected.copy()
    obs[[2, 4, 5, 6, 7]] -= 30  # one isolated dip, then 4 in a row
    alert = growth_alert(obs, expected, sigma=10, k=2, n=3)
    assert alert.tolist() == [False] * 6 + [True, True, False, False]
    high = expected + 30
    assert not growth_alert(high, expected, 10).any()  # faster growth: no alert by default
    assert growth_alert(high, expected, 10, two_sided=True).sum() == 8
