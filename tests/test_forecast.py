"""Level 2 forecast (docs/06 §4): windowing, ONNX export / runtime of an untrained GRU, and
the rules on top of it with a stub forecaster. No training here."""

from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from edge.controller import forecast as F
from edge.controller.state import GreenhouseState

from .controller_utils import NIGHT, NOON, ctx, feed, greenhouse, minutes


def synthetic(hours=40, zone=None):
    idx = pd.date_range("2026-07-01", periods=hours * 6, freq="10min", tz="UTC")
    h = idx.hour.to_numpy()
    df = pd.DataFrame(
        {
            "ts": idx,
            "temperature": 20 + 5 * np.sin(h / 24 * 2 * np.pi),
            "humidite": 70.0,
            "pression": np.linspace(1010, 1000, len(idx)),
            "etat_ventilo": (h > 12).astype(float),
        }
    )
    if zone:
        df["zone"] = zone
    return df


def test_prepare_grid_and_derived_features():
    frame = F.prepare(synthetic())
    assert list(frame.columns) == F.FEATURES and len(frame) == 240
    assert frame["ph"].isna().all()  # missing columns exist, as NaN
    assert frame["pression_tendance_3h"].iloc[-1] == pytest.approx(-10 / 239 * 18, rel=1e-3)
    assert frame["h_sin"].between(-1, 1).all()


def test_make_windows_shapes_and_masks():
    x = np.arange(300 * 2, dtype=np.float32).reshape(300, 2)
    y = np.stack([np.arange(300, dtype=np.float32), np.full(300, np.nan, np.float32)], 1)
    X, Y = F.make_windows(x, y, window=10, horizons=(1, 5))
    assert X.shape == (300 - 10 - 5 + 1, 10, 2) and Y.shape == (X.shape[0], 4)
    assert X[0, -1, 0] == 18 and Y[0, 0] == 10 and Y[0, 2] == 14  # last row 9, +1 and +5 steps
    assert np.isnan(Y[:, 1]).all()  # missing target kept (masked in the loss)
    X, Y = F.make_windows(x, np.full((300, 2), np.nan, np.float32), window=10, horizons=(1,))
    assert len(X) == 0


def test_split_per_zone():
    df = pd.concat([synthetic(40, "z1"), synthetic(40, "z2")])
    frames, cuts = F._split(df, 0.25)
    assert len(frames) == 2 and cuts == [180, 180]


def test_onnx_export_and_runtime(tmp_path):
    pytest.importorskip("torch")
    pytest.importorskip("onnxruntime")
    norm = F.Norm.fit(F.prepare(synthetic()))
    model = F.build_model(hidden=8, layers=1)  # untrained
    F.export_onnx(model, tmp_path, norm, "gru-test")
    fc = F.Forecaster(tmp_path)
    assert fc.name == "gru-test"
    s = GreenhouseState()
    for i in range(F.WINDOW + 20):
        t = NOON - minutes(10 * (F.WINDOW + 20 - i))
        feed(s, "z1", "temperature", 20.0, t)
        feed(s, "z1", "humidite", 70.0, t)
    pred = fc.predict(F.history_frame(s.zone("z1"), NOON))
    assert set(pred) == set(F.OUTPUTS) and all(np.isfinite(v) for v in pred.values())
    assert fc.predict(F.history_frame(GreenhouseState().zone("z1"), NOON)) is None
    assert F.load_forecaster(tmp_path / "absent") is None


class Stub:
    name = "stub"

    def __init__(self, hr6=90.0, t1=20.0):
        self.hr6, self.t1 = hr6, t1

    def predict(self, frame):
        return {
            (t, h): (
                self.hr6
                if (t, h) == ("humidite", "+6h")
                else self.t1
                if t == "temperature"
                else 1.0
            )
            for t, h in F.OUTPUTS
        }


def test_preventive_ventilation_at_night():
    gh, s = greenhouse(), GreenhouseState()
    feed(s, "z1", "humidite", 80, NIGHT)
    lvl = F.Level2(Stub(hr6=90))
    p = [p for p in lvl.evaluate(ctx(gh, s, "z1", NIGHT)) if p.orders]
    assert p and p[0].niveau == 2 and p[0].preuves.prevision[0].horizon == "+6h"
    assert p[0].orders[0].duree_s == 900
    assert not [p for p in F.Level2(Stub(hr6=90)).evaluate(ctx(gh, s, "z1", NOON)) if p.orders]
    assert not [p for p in F.Level2(Stub(hr6=80)).evaluate(ctx(gh, s, "z1", NIGHT)) if p.orders]
    assert F.Level2(None).evaluate(ctx(gh, s, "z1", NIGHT)) == []


def test_sensor_anomaly_against_forecast():
    gh, s = greenhouse(), GreenhouseState()
    lvl = F.Level2(Stub(hr6=50, t1=20.0), period=timedelta(minutes=10), min_residuals=5)
    t, alerts = NOON, []
    for i in range(30):
        feed(s, "z1", "temperature", 20.0 + 0.1 * (i % 2) if i < 25 else 30.0, t)
        alerts += [p for p in lvl.evaluate(ctx(gh, s, "z1", t)) if p.alerte]
        t += minutes(10)
    assert alerts and "suspect" in alerts[0].alerte.message
    assert alerts[0].regle.id == "prevision.anomalie_capteur"
