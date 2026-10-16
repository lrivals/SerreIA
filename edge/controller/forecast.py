"""Level 2, forecasting with a recurrent network (docs/06 §4).

    python -m edge.controller.forecast train --donnees historique.parquet --out edge/models/forecast
    python -m edge.controller.forecast train --sim-jours 60   # mechanics check (simulator)

- Inputs, a 24 h window at a 10 min step: sensors (with the 3 h pressure trend of the
  BMP280), actuator states, outside temperature (weather API, simulator), hour and season
  (sin / cos), vision outputs (anomaly score, green area).
- Outputs: T, HR, pH and EC at +1 h and +6 h.
- Model: GRU (Temporal Fusion Transformer later if the data allow it), trained with torch
  (`vision` extra) and exported to ONNX; the Pi runs it with onnxruntime, like edge/vision.
- Usage: anticipation (`prevision.humidite.ventilation_preventive`: HR forecast > 85 % at
  night → preventive ventilation against mildew) and sensor anomaly detection (measure far
  from the +1 h forecast made one hour earlier, beyond k sigma of the past residuals).

Training data: a wide table (`ts` column + feature columns, missing ones allowed), exported
from TimescaleDB or produced by `sim.dataset`. Until weeks of real data exist, train on the
simulator to validate the mechanics only.
"""

import argparse
import json
import logging
import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from common.mqtt import Actuator, PreuvePrevision, Preuves, SensorType

from .context import Ctx
from .decisions import AlertSpec, Order, Proposal, evidence, fmt, rule
from .state import ZoneState
from .vision_alerts import abnormal_score

log = logging.getLogger(__name__)

STEP = timedelta(minutes=10)
WINDOW = 144  # 24 h
HORIZONS = {"+1h": 6, "+6h": 36}  # in steps
SENSORS = [
    "temperature",
    "humidite",
    "pression",
    "lux",
    "co2",
    "ph",
    "ec",
    "temp_eau",
    "humidite_sol",
]
ACTUATORS = [f"etat_{a.value}" for a in Actuator]
EXTRA = ["t_ext", "vision_anomalie", "surface_verte"]
DERIVED = ["pression_tendance_3h", "h_sin", "h_cos", "j_sin", "j_cos"]
FEATURES = SENSORS + ACTUATORS + EXTRA + DERIVED
TARGETS = ["temperature", "humidite", "ph", "ec"]
OUTPUTS = [(t, h) for h in HORIZONS for t in TARGETS]  # model output order
MIN_SIGMA = {"temperature": 0.3, "humidite": 2.0, "ph": 0.05, "ec": 0.05}
MODEL_FILE, META_FILE = "forecast.onnx", "meta.json"


# --- data -------------------------------------------------------------------------------


def prepare(df):
    """Wide frame (DatetimeIndex or `ts` column) -> regular 10 min grid with every FEATURE."""
    import pandas as pd

    if "ts" in df.columns:
        df = df.set_index(pd.to_datetime(df["ts"], utc=True)).drop(columns="ts")
    df = df.sort_index()
    cols = [c for c in SENSORS + ACTUATORS + EXTRA if c in df.columns]
    out = df[cols].astype(float).resample(STEP).mean()
    out = out.reindex(columns=SENSORS + ACTUATORS + EXTRA)
    out[SENSORS + EXTRA] = out[SENSORS + EXTRA].ffill(limit=6)  # 1 h gap at most
    out[ACTUATORS] = out[ACTUATORS].ffill()  # a state holds until the next change
    out["pression_tendance_3h"] = out["pression"] - out["pression"].shift(18)
    idx = out.index
    hour = (idx.hour + idx.minute / 60) / 24 * 2 * math.pi
    day = idx.dayofyear / 365.25 * 2 * math.pi
    out["h_sin"], out["h_cos"] = np.sin(hour), np.cos(hour)
    out["j_sin"], out["j_cos"] = np.sin(day), np.cos(day)
    return out[FEATURES]


@dataclass
class Norm:
    mean: dict[str, float]
    std: dict[str, float]

    @classmethod
    def fit(cls, frame) -> "Norm":
        mean = frame.mean().fillna(0.0)
        std = frame.std().fillna(1.0).replace(0.0, 1.0)
        return cls(mean.to_dict(), std.to_dict())

    def apply(self, frame, cols: list[str]) -> np.ndarray:
        """Normalised float32 array; missing values -> 0 (the mean)."""
        m = np.array([self.mean[c] for c in cols], np.float32)
        s = np.array([self.std[c] for c in cols], np.float32)
        x = (frame[cols].to_numpy(np.float32) - m) / s
        return np.nan_to_num(x, nan=0.0)


def make_windows(
    x: np.ndarray,
    y: np.ndarray,
    window: int = WINDOW,
    horizons: tuple[int, ...] = tuple(HORIZONS.values()),
):
    """x (T, F), y (T, n_targets) with NaN for missing targets ->
    X (N, window, F), Y (N, n_targets * n_horizons) in OUTPUTS order, NaN kept (masked in
    the loss: a soil zone has no pH / EC). Windows without any target are dropped. The
    window ends at i - 1, targets at i - 1 + h."""
    xs, ys = [], []
    for i in range(window, len(x) - max(horizons) + 1):
        target = np.concatenate([y[i - 1 + h] for h in horizons])
        if np.isnan(target).all():
            continue
        xs.append(x[i - window : i])
        ys.append(target)
    if not xs:
        n_out = y.shape[1] * len(horizons)
        return np.zeros((0, window, x.shape[1]), np.float32), np.zeros((0, n_out), np.float32)
    return np.stack(xs).astype(np.float32), np.stack(ys).astype(np.float32)


def targets_array(frame, norm: Norm) -> np.ndarray:
    """Normalised targets, NaN kept (dropped by make_windows)."""
    m = np.array([norm.mean[c] for c in TARGETS], np.float32)
    s = np.array([norm.std[c] for c in TARGETS], np.float32)
    return (frame[TARGETS].to_numpy(np.float32) - m) / s


# --- model (torch, training only) -------------------------------------------------------


def build_model(
    n_features: int = len(FEATURES),
    n_outputs: int = len(OUTPUTS),
    hidden: int = 64,
    layers: int = 2,
    dropout: float = 0.1,
):
    import torch
    from torch import nn

    class GRUForecaster(nn.Module):
        def __init__(self):
            super().__init__()
            self.gru = nn.GRU(
                n_features, hidden, layers, batch_first=True, dropout=dropout if layers > 1 else 0.0
            )
            self.head = nn.Sequential(
                nn.Linear(hidden, hidden), nn.ReLU(), nn.Linear(hidden, n_outputs)
            )

        def forward(self, x: "torch.Tensor") -> "torch.Tensor":
            out, _ = self.gru(x)
            return self.head(out[:, -1])

    return GRUForecaster()


def export_onnx(model, out_dir: Path, norm: Norm, name: str, window: int = WINDOW) -> Path:
    """Write forecast.onnx + meta.json (features, targets, horizons, normalisation)."""
    import torch

    out_dir.mkdir(parents=True, exist_ok=True)
    model.eval()
    n_features = model.gru.input_size
    torch.onnx.export(
        model,
        torch.zeros(1, window, n_features),
        out_dir / MODEL_FILE,
        input_names=["x"],
        output_names=["y"],  # batch 1: one window per prediction
        opset_version=17,
        dynamo=False,
    )
    meta = {
        "modele": name,
        "features": FEATURES,
        "outputs": [list(o) for o in OUTPUTS],
        "horizons": HORIZONS,
        "step_s": STEP.total_seconds(),
        "window": window,
        "mean": norm.mean,
        "std": norm.std,
    }
    (out_dir / META_FILE).write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    return out_dir / MODEL_FILE


def _split(df, val_frac: float):
    """Per zone (column `zone`, optional): regular grids, chronological train / val cut."""
    groups = (
        [g.drop(columns="zone") for _, g in df.groupby("zone")] if "zone" in df.columns else [df]
    )
    frames = [prepare(g) for g in groups]
    cuts = [int(len(f) * (1 - val_frac)) for f in frames]
    return frames, cuts


def train(
    df,
    out_dir: Path,
    name: str = "gru-v1",
    epochs: int = 30,
    hidden: int = 64,
    layers: int = 2,
    lr: float = 1e-3,
    batch: int = 128,
    val_frac: float = 0.2,
    device: str = "cpu",
) -> dict:
    """Chronological split (the last `val_frac` of each zone for validation), best epoch on
    the masked val MAE, exported to ONNX. Returns the validation MAE per (target, horizon)
    in physical units."""
    import pandas as pd
    import torch

    frames, cuts = _split(df, val_frac)
    norm = Norm.fit(pd.concat([f.iloc[:c] for f, c in zip(frames, cuts, strict=True)]))
    parts = {"tr": [], "va": []}
    for f, c in zip(frames, cuts, strict=True):
        x, y = norm.apply(f, FEATURES), targets_array(f, norm)
        parts["tr"].append(make_windows(x[:c], y[:c]))
        parts["va"].append(make_windows(x[max(0, c - WINDOW) :], y[max(0, c - WINDOW) :]))
    xtr, ytr = (np.concatenate([p[k] for p in parts["tr"]]) for k in (0, 1))
    xva, yva = (np.concatenate([p[k] for p in parts["va"]]) for k in (0, 1))
    if len(xtr) == 0 or len(xva) == 0:
        raise ValueError(f"historique trop court : {sum(len(f) for f in frames)} pas de 10 min")
    log.info("fenêtres : %d entraînement, %d validation", len(xtr), len(xva))

    model = build_model(len(FEATURES), len(OUTPUTS), hidden, layers).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)

    def masked(pred, target):
        mask = ~torch.isnan(target)
        err = torch.nn.functional.smooth_l1_loss(pred[mask], target[mask], reduction="mean")
        return err

    xtr_t, ytr_t = torch.from_numpy(xtr), torch.from_numpy(ytr)
    xva_t, yva_t = torch.from_numpy(xva).to(device), torch.from_numpy(yva).to(device)
    best, best_state = float("inf"), None
    for epoch in range(epochs):
        model.train()
        perm = torch.randperm(len(xtr_t))
        for i in range(0, len(perm), batch):
            j = perm[i : i + batch]
            opt.zero_grad()
            loss = masked(model(xtr_t[j].to(device)), ytr_t[j].to(device))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
        model.eval()
        with torch.no_grad():
            d = model(xva_t) - yva_t
            val = d[~torch.isnan(d)].abs().mean().item()
        log.info("époque %d : MAE val (normalisée) %.4f", epoch + 1, val)
        if val < best:
            best, best_state = (
                val,
                {k: v.detach().cpu().clone() for k, v in model.state_dict().items()},
            )
    model.load_state_dict(best_state)
    model.cpu().eval()
    with torch.no_grad():
        pred = model(torch.from_numpy(xva)).numpy()
    std = np.array([norm.std[t] for t, _ in OUTPUTS], np.float32)
    errors = np.nanmean(np.abs(pred - yva), axis=0) * std
    mae = {f"{t} {h}": float(v) for (t, h), v in zip(OUTPUTS, errors, strict=True)}
    export_onnx(model, out_dir, norm, name)
    (out_dir / "metriques.json").write_text(json.dumps(mae, indent=2, ensure_ascii=False))
    return mae


# --- runtime (onnxruntime, Pi) ------------------------------------------------------------


def history_frame(zs: ZoneState, now: datetime):
    """Wide frame of the last 24 h of a zone, from the controller state."""
    import pandas as pd

    start = now - STEP * (WINDOW + 18)  # + the pressure trend lag
    cols = {}
    for name, hist in zs.history.items():
        if name in SENSORS or name in ACTUATORS:
            pts = [(t, v) for t, v in hist if t >= start]
            if name in ACTUATORS and not pts and name.removeprefix("etat_") in zs.actuators:
                pts = [(start, zs.actuator_level(name.removeprefix("etat_")))]  # held state
            if pts:
                cols[name] = pd.Series(
                    [v for _, v in pts], index=pd.DatetimeIndex([t for t, _ in pts])
                )
    vis = [(r.ts, abnormal_score(r), r.surface_verte_px) for r in zs.vision if r.ts >= start]
    if vis:
        idx = pd.DatetimeIndex([t for t, _, _ in vis])
        cols["vision_anomalie"] = pd.Series([a for _, a, _ in vis], index=idx)
        cols["surface_verte"] = pd.Series([float(s) for _, _, s in vis], index=idx)
    frame = pd.DataFrame(cols)
    grid = pd.date_range(start, now, freq=STEP, tz="UTC")
    frame = pd.concat([frame, pd.DataFrame(index=grid)]).sort_index()
    return frame[~frame.index.duplicated()]


class Forecaster:
    """ONNX model + meta.json written by `export_onnx`."""

    def __init__(self, model_dir: Path):
        import onnxruntime as ort

        self.meta = json.loads((model_dir / META_FILE).read_text())
        self.name = self.meta["modele"]
        self.window = self.meta["window"]
        self.outputs = [tuple(o) for o in self.meta["outputs"]]
        self.norm = Norm(self.meta["mean"], self.meta["std"])
        self.session = ort.InferenceSession(
            str(model_dir / MODEL_FILE), providers=["CPUExecutionProvider"]
        )

    def predict(self, frame) -> dict[tuple[str, str], float] | None:
        """Forecast from a wide history frame; None if less than a full window of data."""
        grid = prepare(frame)
        if len(grid) < self.window or grid[SENSORS].iloc[-self.window :].notna().sum().sum() == 0:
            return None
        x = self.norm.apply(grid.iloc[-self.window :], self.meta["features"])[None]
        y = self.session.run(None, {"x": x})[0][0]
        return {
            (t, h): float(v * self.norm.std[t] + self.norm.mean[t])
            for (t, h), v in zip(self.outputs, y, strict=True)
        }


def load_forecaster(path: Path | None) -> Forecaster | None:
    if path is None or not (path / MODEL_FILE).exists():
        log.info("pas de modèle de prévision (%s) : niveau 2 désactivé", path)
        return None
    return Forecaster(path)


# --- level 2 rules ------------------------------------------------------------------------


@dataclass
class Residuals:
    """EWMA of the squared +1 h forecast errors of one quantity."""

    floor: float
    alpha: float = 0.02
    var: float | None = None
    n: int = 0

    @property
    def sigma(self) -> float:
        return max(self.floor, math.sqrt(self.var or 0.0))

    def update(self, r: float) -> None:
        self.var = r * r if self.var is None else (1 - self.alpha) * self.var + self.alpha * r * r
        self.n += 1


@dataclass
class Level2:
    forecaster: Forecaster | None
    period: timedelta = STEP
    min_residuals: int = 20
    last: dict[str, datetime] = field(default_factory=dict)
    predictions: dict[str, dict[tuple[str, str], float]] = field(default_factory=dict)
    due: dict[str, deque] = field(default_factory=dict)  # zone -> (due ts, grandeur, value)
    residuals: dict[tuple[str, str], Residuals] = field(default_factory=dict)

    def evaluate(self, ctx: Ctx) -> list[Proposal]:
        if self.forecaster is None:
            return []
        out = self._anomalies(ctx)
        last = self.last.get(ctx.zone)
        if last is None or ctx.now - last >= self.period:
            self.last[ctx.zone] = ctx.now
            pred = self.forecaster.predict(history_frame(ctx.zs, ctx.now))
            if pred is not None:
                self.predictions[ctx.zone] = pred
                q = self.due.setdefault(ctx.zone, deque())
                for t in TARGETS:
                    q.append((ctx.now + STEP * HORIZONS["+1h"], t, pred[(t, "+1h")]))
        return out + self._preventive(ctx)

    def _anomalies(self, ctx: Ctx) -> list[Proposal]:
        out, q, k = [], self.due.get(ctx.zone, deque()), ctx.gh.cfg.prevision.ecart_sigma
        while q and q[0][0] <= ctx.now:
            _, grandeur, predicted = q.popleft()
            measured = ctx.value(grandeur)
            if measured is None:
                continue
            res = self.residuals.setdefault((ctx.zone, grandeur), Residuals(MIN_SIGMA[grandeur]))
            r = measured - predicted
            if res.n >= self.min_residuals and abs(r) > k * res.sigma:
                reading = ctx.reading(grandeur)
                msg = (
                    f"{grandeur} mesurée {fmt(measured, 2)} loin de la prévision "
                    f"{fmt(predicted, 2)} "
                    f"(écart {fmt(abs(r) / res.sigma)} σ) : capteur {reading.noeud} suspect ?"
                )
                out.append(
                    Proposal(
                        zone=ctx.zone,
                        regle=rule("prevision.anomalie_capteur"),
                        niveau=2,
                        type="exceptionnelle",
                        explication=msg,
                        alerte=AlertSpec(
                            "warning",
                            f"{ctx.zone} : {msg}",
                            f"{ctx.zone}/prevision.anomalie/{grandeur}",
                        ),
                        preuves=Preuves(
                            capteurs=[evidence(ctx.zone, grandeur, reading)],
                            prevision=[
                                PreuvePrevision(
                                    grandeur=grandeur,
                                    horizon="+1h",
                                    valeur=round(predicted, 3),
                                    modele=self.forecaster.name,
                                )
                            ],
                        ),
                    )
                )
            else:
                res.update(r)
        return out

    def _preventive(self, ctx: Ctx) -> list[Proposal]:
        cfg = ctx.gh.cfg.prevision
        pred = self.predictions.get(ctx.zone)
        rid = "prevision.humidite.ventilation_preventive"
        act = ctx.act(Actuator.VENTILO)
        if pred is None or ctx.jour or act is None:
            return []
        hr6 = pred[("humidite", "+6h")]
        fired = ctx.zs.rule_fired.get(rid)
        if hr6 <= cfg.hr_max_nuit or (fired and ctx.now - fired < timedelta(hours=1)):
            return []
        msg = (
            f"HR prévue à +6 h {fmt(hr6)} % > {cfg.hr_max_nuit:g} % la nuit "
            f"→ ventilation préventive {cfg.ventilation_s / 60:g} min"
        )
        order = (
            Order(Actuator.VENTILO, "pwm", 100.0, cfg.ventilation_s, msg)
            if act.commande == "pwm"
            else Order(Actuator.VENTILO, "on", None, cfg.ventilation_s, msg)
        )
        hr = ctx.reading(SensorType.HUMIDITE)
        return [
            Proposal(
                zone=ctx.zone,
                regle=rule(rid),
                niveau=2,
                type="exceptionnelle",
                explication=msg,
                orders=[order],
                preuves=Preuves(
                    capteurs=[evidence(ctx.zone, SensorType.HUMIDITE, hr)] if hr else [],
                    prevision=[
                        PreuvePrevision(
                            grandeur="humidite",
                            horizon="+6h",
                            valeur=round(hr6, 2),
                            modele=self.forecaster.name,
                        )
                    ],
                    consignes=ctx.sp.as_evidence() if ctx.sp else {},
                ),
            )
        ]


# --- CLI --------------------------------------------------------------------------------


def main() -> None:
    from .config import ROOT

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train", help="entraîner le GRU et l'exporter en ONNX")
    src = t.add_mutually_exclusive_group(required=True)
    src.add_argument("--donnees", type=Path, help="table large .parquet / .csv (colonne ts)")
    src.add_argument("--sim-jours", type=int, help="historique simulé (sim.dataset)")
    t.add_argument("--out", type=Path, default=Path("edge/models/forecast"))
    t.add_argument("--nom", default="gru-v1")
    t.add_argument("--epochs", type=int, default=30)
    t.add_argument("--hidden", type=int, default=64)
    t.add_argument("--device", default="cpu")
    t.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    if args.donnees:
        import pandas as pd

        path = args.donnees
        df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
    else:
        from sim.dataset import generate

        df = generate(days=args.sim_jours, seed=args.seed)
    out = args.out if args.out.is_absolute() else ROOT / args.out
    mae = train(df, out, args.nom, args.epochs, args.hidden, device=args.device)
    for k, v in mae.items():
        print(f"MAE {k} : {v:.3f}")
    print(f"modèle : {out / MODEL_FILE}")


if __name__ == "__main__":
    main()
