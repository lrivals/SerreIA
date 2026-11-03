"""Forecast baselines (docs/22 L14): persistence, LightGBM features without look-ahead,
evaluation with a skill score, and the LightGBM runtime behind `load_forecaster`."""

import numpy as np
import pandas as pd
import pytest

from edge.controller import forecast as F
from edge.controller import forecast_baselines as B
from edge.controller.state import GreenhouseState

from .controller_utils import NIGHT, ctx, feed, greenhouse, minutes


def daily(days=12, noise=0.0, seed=0, zone="z1"):
    """Temperature and HR on an exact 24 h cycle (+ noise), a fan switching at noon."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-07-01", periods=days * 144, freq="10min", tz="UTC")
    phase = (idx.hour.to_numpy() * 60 + idx.minute.to_numpy()) / 1440 * 2 * np.pi
    n = len(idx)
    return pd.DataFrame(
        {
            "ts": idx,
            "zone": zone,
            "temperature": 20 + 5 * np.sin(phase) + noise * rng.standard_normal(n),
            "humidite": 70 - 10 * np.sin(phase) + noise * rng.standard_normal(n),
            "t_ext": 15 + 5 * np.sin(phase),
            "etat_ventilo": (idx.hour.to_numpy() >= 12).astype(float),
        }
    )


def test_persistence_has_zero_skill_and_seasonal_is_exact_on_a_daily_cycle():
    res = B.evaluate(daily(), lgbm=False)
    for key in ("temperature +1h", "humidite +6h"):
        assert res[key]["persistance"]["skill"] == 0
    assert res["temperature +6h"]["persistance_24h"]["rmse"] == pytest.approx(0, abs=1e-6)
    assert res["temperature +6h"]["persistance"]["rmse"] > 1
    assert "ph +1h" not in res  # no pH in this zone: nothing to score
    assert "persistance" in B.markdown(res)


def test_features_use_the_past_only():
    grid = F.prepare(daily(days=2))
    before = B.lgbm_features(grid).iloc[100]
    grid.iloc[101:, grid.columns.get_loc("temperature")] = 99.0  # the future changes
    after = B.lgbm_features(grid).iloc[100]
    pd.testing.assert_series_equal(before, after)


def test_minutes_since_the_last_actuator_change():
    s = pd.Series([np.nan, 0, 0, 1, 1, 1, 0], dtype=float)
    out = B._minutes_since_change(s).tolist()
    assert np.isnan(out[0]) and out[1:] == [0, 10, 0, 10, 20, 0]


def test_lgbm_beats_persistence_at_6h():
    pytest.importorskip("lightgbm")
    res = B.evaluate(daily(days=14, noise=0.3))
    r = res["temperature +6h"]
    assert r["lgbm"]["skill"] > 0.5 and r["persistance"]["skill"] == 0


def test_lgbm_saved_model_runs_in_level2(tmp_path):
    pytest.importorskip("lightgbm")
    frames, _ = F._split(daily(days=6), 0.0)
    B.LGBMModel("lgbm-test", {"verbose": -1}).fit(frames).save(tmp_path)
    fc = F.load_forecaster(tmp_path)
    assert isinstance(fc, B.LGBMForecaster) and fc.name == "lgbm-test"
    gh, s = greenhouse(), GreenhouseState()
    for i in range(40):
        t = NIGHT - minutes(10 * (40 - i))
        feed(s, "z1", "temperature", 18.0 + 0.01 * i, t)
        feed(s, "z1", "humidite", 92.0, t)
    pred = fc.predict(F.history_frame(s.zone("z1"), NIGHT))
    assert {("temperature", "+1h"), ("humidite", "+6h"), ("humidite", "+10min")} <= set(pred)
    assert ("ph", "+1h") not in pred  # no pH measured in z1
    lvl = F.Level2(fc)
    lvl.evaluate(ctx(gh, s, "z1", NIGHT))  # the level 2 rules accept its predictions
    assert lvl.predictions["z1"][("humidite", "+6h")] == pred[("humidite", "+6h")]
    assert fc.predict(F.history_frame(GreenhouseState().zone("z1"), NIGHT)) is None
