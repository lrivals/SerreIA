"""Forecast baselines before the GRU (docs/22 L14): persistence, LightGBM, evaluation.

    python -m edge.controller.forecast evaluate --sim-jours 60
    python -m edge.controller.forecast train --modele lgbm --sim-jours 60

- `Persistence`: the last value. `SeasonalPersistence`: the value 24 h before the target
  time. The skill score of a model is `1 − RMSE / RMSE_persistance`: 0 for the persistence
  itself by construction, > 0 only when the model beats it.
- `LGBMModel`: one LightGBM regressor per (target, horizon) on engineered features of the
  past only: lags 10–60 min, rolling means 30/60/120 min, inside − outside temperature,
  minutes since the last change of each actuator (the worst errors are at fan switches,
  `2025-cebolla-alemany#013.1`, `#005.2`). Runs on the Pi without torch (`LGBMForecaster`,
  same `predict` as the ONNX `Forecaster`, chosen by `meta.json["type"]`).
- `evaluate`: chronological split per zone (the last `test_frac` of each zone, never seen in
  training), MAE / RMSE / skill per target, horizon and model. The GRU is only deployed if it
  beats LightGBM on this test (docs/22 L14). On the simulator the models learn the equations
  of the simulator: only the comparison on real data counts.
"""

import json
import math
from pathlib import Path

import numpy as np

from .forecast import (
    ACTUATORS,
    DERIVED,
    META_FILE,
    MODEL_FILE,
    SENSORS,
    STEP,
    TARGETS,
    Norm,
    _split,
    prepare,
)

HORIZONS = {"+10min": 1, "+1h": 6, "+6h": 36}  # in 10 min steps
SEASON = 144  # 24 h
LAGS = range(1, 7)  # 10 to 60 min
ROLLING = (3, 6, 12)  # 30, 60, 120 min
MIN_ROWS = max(ROLLING)  # rows of history needed for one prediction
LGBM_PARAMS = dict(learning_rate=0.05, num_leaves=31, min_data_in_leaf=20, verbose=-1)
LGBM_ROUNDS = 300
MODELS = ("persistance", "persistance_24h", "lgbm", "gru")


# --- baselines ----------------------------------------------------------------------------


class Persistence:
    name = "persistance"

    @staticmethod
    def predict_grid(grid, target: str, h: int):
        return grid[target]


class SeasonalPersistence:
    name = "persistance_24h"

    @staticmethod
    def predict_grid(grid, target: str, h: int):
        return grid[target].shift(SEASON - h)  # value at (t + h) − 24 h


# --- LightGBM -----------------------------------------------------------------------------


def lgbm_features(grid):
    """Features at each row from that row and the past only (no look-ahead)."""
    import pandas as pd

    cols = {}
    for c in SENSORS + ["t_ext", "vision_anomalie", "surface_verte"] + DERIVED:
        if c in grid.columns:
            cols[c] = grid[c]
    for c in TARGETS:
        for k in LAGS:
            cols[f"{c}_lag{k}"] = grid[c].shift(k)
        for w in ROLLING:
            cols[f"{c}_moy{w}"] = grid[c].rolling(w, min_periods=1).mean()
    cols["ecart_ext"] = grid["temperature"] - grid["t_ext"]
    for a in ACTUATORS:
        cols[a] = grid[a]
        cols[f"{a}_depuis_min"] = _minutes_since_change(grid[a])
    return pd.DataFrame(cols, index=grid.index)


def _minutes_since_change(s):
    """Minutes since the value of an actuator state last changed (NaN before any value)."""
    import pandas as pd

    v = s.to_numpy(float)
    out = np.full(len(v), np.nan)
    since, prev = np.nan, np.nan
    step_min = STEP.total_seconds() / 60
    for i, x in enumerate(v):
        if np.isnan(x):
            since = since + step_min if not np.isnan(since) else np.nan
        elif np.isnan(prev) or x != prev:
            since, prev = 0.0, x
        else:
            since += step_min
        out[i] = since
    return pd.Series(out, index=s.index)


def _targets(grid, target: str, h: int):
    return grid[target].shift(-h)


class LGBMModel:
    """One regressor per (target, horizon); targets missing in a zone are skipped."""

    def __init__(self, name: str = "lgbm-v1", params: dict | None = None):
        self.name = name
        self.params = {**LGBM_PARAMS, **(params or {})}
        self.boosters: dict[tuple[str, str], object] = {}
        self.features: list[str] = []

    def fit(self, grids: list, cuts: list[int] | None = None) -> "LGBMModel":
        """Fit on each grid up to its cut (rows whose target lies after the cut are
        dropped: no test value leaks into training)."""
        import lightgbm as lgb
        import pandas as pd

        feats = [lgbm_features(g) for g in grids]
        self.features = list(feats[0].columns)
        for t in TARGETS:
            for hname, h in HORIZONS.items():
                xs, ys = [], []
                for g, f, c in zip(grids, feats, cuts or [len(g) for g in grids], strict=True):
                    y = _targets(g, t, h)
                    keep = np.zeros(len(g), bool)
                    keep[: max(0, c - h)] = True
                    keep &= y.notna().to_numpy() & g[t].notna().to_numpy()
                    xs.append(f[keep])
                    ys.append(y[keep])
                x, y = pd.concat(xs), pd.concat(ys)
                if len(x) < 50:
                    continue  # target absent (no pH / EC in a soil zone…)
                data = lgb.Dataset(x[self.features], y.to_numpy(float))
                self.boosters[(t, hname)] = lgb.train(
                    {"objective": "regression", **self.params}, data, LGBM_ROUNDS
                )
        return self

    def predict_grid(self, grid, target: str, hname: str):
        import pandas as pd

        booster = self.boosters.get((target, hname))
        if booster is None:
            return pd.Series(np.nan, index=grid.index)
        f = lgbm_features(grid)[self.features]
        out = pd.Series(booster.predict(f), index=grid.index)
        return out.where(grid[target].notna())

    def save(self, out_dir: Path) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        files = {}
        for (t, h), b in self.boosters.items():
            name = f"lgbm_{t}_{h.strip('+')}.txt"
            b.save_model(str(out_dir / name))
            files[f"{t} {h}"] = name
        meta = {
            "type": "lgbm",
            "modele": self.name,
            "features": self.features,
            "horizons": HORIZONS,
            "step_s": STEP.total_seconds(),
            "fichiers": files,
        }
        (out_dir / META_FILE).write_text(json.dumps(meta, indent=2, ensure_ascii=False))
        stale = out_dir / MODEL_FILE  # a previous GRU in the same directory
        if stale.exists():
            stale.unlink()
        return out_dir / META_FILE


class LGBMForecaster:
    """Runtime of a saved `LGBMModel` (Pi, no torch); same interface as `Forecaster`."""

    def __init__(self, model_dir: Path):
        import lightgbm as lgb

        self.meta = json.loads((model_dir / META_FILE).read_text())
        self.name = self.meta["modele"]
        self.features = self.meta["features"]
        self.boosters = {
            tuple(k.split(" ")): lgb.Booster(model_file=str(model_dir / f))
            for k, f in self.meta["fichiers"].items()
        }

    def predict(self, frame) -> dict[tuple[str, str], float] | None:
        """Forecast from a wide history frame; None without enough recent data."""
        grid = prepare(frame)
        if len(grid) < MIN_ROWS or grid[SENSORS].iloc[-MIN_ROWS:].notna().sum().sum() == 0:
            return None
        row = lgbm_features(grid).iloc[[-1]][self.features]
        out = {}
        for (t, h), b in self.boosters.items():
            if not math.isnan(grid[t].iloc[-1]):
                out[(t, h)] = float(b.predict(row)[0])
        return out


# --- evaluation ---------------------------------------------------------------------------


def _gru_predictions(gru_dir: Path, grid, start: int):
    """+1 h / +6 h predictions of an ONNX GRU (`forecast.Forecaster`) at each row ≥ start,
    from the same grid and window as at runtime."""
    import onnxruntime as ort
    import pandas as pd

    meta = json.loads((gru_dir / META_FILE).read_text())
    norm, window = Norm(meta["mean"], meta["std"]), meta["window"]
    session = ort.InferenceSession(str(gru_dir / MODEL_FILE), providers=["CPUExecutionProvider"])
    x = norm.apply(grid, meta["features"])
    outputs = [tuple(o) for o in meta["outputs"]]
    preds = {o: pd.Series(np.nan, index=grid.index) for o in outputs}
    for i in range(max(start, window - 1), len(grid)):
        y = session.run(None, {"x": x[i - window + 1 : i + 1][None]})[0][0]
        for (t, h), v in zip(outputs, y, strict=True):
            preds[(t, h)].iloc[i] = v * norm.std[t] + norm.mean[t]
    return preds


def evaluate(df, test_frac: float = 0.2, gru_dir: Path | None = None, lgbm=True) -> dict:
    """MAE, RMSE and skill score per (target, horizon, model) on the last `test_frac` of
    each zone. All models are scored on the same rows: target known and every prediction
    available."""
    frames, cuts = _split(df, test_frac)
    model = LGBMModel().fit(frames, cuts) if lgbm else None
    gru = gru_dir is not None and (gru_dir / MODEL_FILE).exists()
    results: dict = {}
    for t in TARGETS:
        for hname, h in HORIZONS.items():
            errs: dict[str, list] = {m: [] for m in MODELS}
            for g, c in zip(frames, cuts, strict=True):
                y = _targets(g, t, h).to_numpy(float)
                preds = {
                    "persistance": Persistence.predict_grid(g, t, h).to_numpy(float),
                    "persistance_24h": SeasonalPersistence.predict_grid(g, t, h).to_numpy(float),
                }
                if model is not None:
                    preds["lgbm"] = model.predict_grid(g, t, hname).to_numpy(float)
                if gru and hname in ("+1h", "+6h"):
                    preds["gru"] = _gru_predictions(gru_dir, g, c)[(t, hname)].to_numpy(float)
                rows = np.arange(len(g)) >= c
                rows &= ~np.isnan(y)
                for p in preds.values():
                    rows &= ~np.isnan(p)
                for m, p in preds.items():
                    errs[m].append(p[rows] - y[rows])
            ref = None
            for m in MODELS:
                e = np.concatenate(errs[m]) if errs[m] else np.array([])
                if len(e) == 0:
                    continue
                rmse = float(np.sqrt(np.mean(e**2)))
                if m == "persistance":
                    ref = rmse
                skill = 1 - rmse / ref if ref else float("nan")
                results.setdefault(f"{t} {hname}", {})[m] = {
                    "mae": float(np.mean(np.abs(e))),
                    "rmse": rmse,
                    "skill": skill,
                    "n": int(len(e)),
                }
    return results


def markdown(results: dict) -> str:
    models = [m for m in MODELS if any(m in r for r in results.values())]
    head = "| Cible, horizon | n | " + " | ".join(f"{m} RMSE (skill)" for m in models) + " |"
    lines = [head, "|" + "---|" * (len(models) + 2)]
    for key, r in results.items():
        n = next(iter(r.values()))["n"]
        cells = []
        for m in models:
            v = r.get(m)
            cells.append("—" if v is None else f"{v['rmse']:.3f} ({v['skill']:+.2f})")
        lines.append(f"| {key} | {n} | " + " | ".join(cells) + " |")
    return "\n".join(lines)
