"""Expected growth curve and deviation alert (docs/04 §5, steps 3 and 4).

Per crop, a logistic curve y(t) = K / (1 + exp(−r (t − t0))) is fitted on previous cycles
(t: days since planting, y: green area or height). A plant is flagged when its measure stays
more than k·σ (σ: residual spread of the fit) away from the curve for N consecutive captures:
one bad capture (shadow, reflection) never raises an alert alone.
"""

from dataclasses import asdict, dataclass

import numpy as np
from scipy.optimize import curve_fit


def logistic(t: np.ndarray, k: float, r: float, t0: float) -> np.ndarray:
    return k / (1 + np.exp(-r * (np.asarray(t, float) - t0)))


@dataclass
class GrowthCurve:
    k: float  # plateau
    r: float  # growth rate (1/day)
    t0: float  # inflection (day)
    sigma: float  # residual standard deviation of the fit

    def __call__(self, t) -> np.ndarray:
        return logistic(t, self.k, self.r, self.t0)

    def as_dict(self) -> dict:
        return asdict(self)


def fit_logistic(t, y) -> GrowthCurve:
    """Least-squares logistic fit (several cycles can be concatenated)."""
    t, y = np.asarray(t, float), np.asarray(y, float)
    ok = np.isfinite(t) & np.isfinite(y)
    t, y = t[ok], y[ok]
    if len(t) < 4:
        raise ValueError("au moins 4 mesures pour ajuster une logistique")
    span = max(float(np.ptp(t)), 1.0)
    p0 = (float(y.max()) * 1.1, 4.0 / span, float(np.median(t)))
    bounds = ([0, 0, t.min() - span], [np.inf, np.inf, t.max() + span])
    (k, r, t0), _ = curve_fit(logistic, t, y, p0=p0, bounds=bounds, maxfev=10000)
    sigma = float(np.std(y - logistic(t, k, r, t0), ddof=3)) if len(t) > 3 else 0.0
    return GrowthCurve(float(k), float(r), float(t0), sigma)


def growth_alert(
    obs, expected, sigma: float, k: float = 2.0, n: int = 3, two_sided: bool = False
) -> np.ndarray:
    """Boolean per capture: alert active (N consecutive deviations beyond k·σ, the last
    one included). Default: only slower growth (obs below the curve) counts."""
    dev = np.asarray(obs, float) - np.asarray(expected, float)
    out_of_band = np.abs(dev) > k * sigma if two_sided else dev < -k * sigma
    run = np.zeros(len(dev), int)
    for i, bad in enumerate(out_of_band):
        run[i] = (run[i - 1] + 1 if i else 1) if bad else 0
    return run >= n
