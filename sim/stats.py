"""Statistics of the sensor and actuator series (docs/19 §5), for the notebook 08.

Sources: a frozen scenario (`data/scenarios/<nom>/serre.db`), any SQLite database with the
backend schema (`mesure`, `etat_actionneur`, `alerte`, `vision_resultat`, `serre`), or the
wide table of `sim.dataset.generate`, converted to the same long format by `from_sim`.

Long format of the measurements: `ts` (UTC), `capteur_id`, `noeud`, `zone`, `type`,
`valeur`, `qualite`. Actuator states: `ts`, `zone`, `actionneur`, `action`, `valeur`.
Thresholds are parameters with documented defaults.
"""

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_DIR = ROOT / "data" / "scenarios"
GAP_FACTOR = 2.0  # gap: interval > GAP_FACTOR × the sensor's median cadence
LUX_VERS_PPFD = 0.0185  # default of the serre table (docs/09 §5)

# Physical bounds per sensor type: a value outside is a sensor or wiring defect, not a
# greenhouse state. Wide on purpose; the controller's own limits are in serre.yaml.
PHYSICAL_BOUNDS: dict[str, tuple[float, float]] = {
    "temperature": (-20.0, 60.0),  # °C, air
    "temp_eau": (0.0, 50.0),  # °C
    "humidite": (0.0, 100.0),  # % RH
    "humidite_sol": (0.0, 100.0),  # %
    "co2": (0.0, 10_000.0),  # ppm
    "lux": (0.0, 200_000.0),  # lx (full sun ≈ 100 klx)
    "pression": (800.0, 1100.0),  # hPa
    "ph": (0.0, 14.0),
    "ec": (0.0, 10.0),  # mS/cm
    "niveau_cuve": (0.0, 100.0),  # %
    "presence": (0.0, 3.0),  # radar targets
}
# Saturation of the sensor (BH1750: 16-bit counter): readings stuck at the top of the range.
SATURATION: dict[str, float] = {"lux": 65535.0}
# Actuator -> sensor it acts on (§5.4 command -> effect).
DEFAULT_PAIRS: tuple[tuple[str, str], ...] = (
    ("ventilo", "temperature"),
    ("chauffage", "temperature"),
    ("brumisateur", "humidite"),
    ("pompe_nutri", "humidite_sol"),
)
ACTIVE = ("on", "pwm")
NO_OUTLIER = ("presence",)  # discrete sensors, no robust z-score


# ------------------------------------------------------------------------------ loading


def _read(db: Path, sql: str) -> pd.DataFrame:
    with sqlite3.connect(Path(db)) as con:
        return pd.read_sql_query(sql, con)


def _utc(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, utc=True, format="ISO8601")


def load_long(db: Path) -> pd.DataFrame:
    df = _read(db, "SELECT ts, capteur_id, noeud, zone, type, valeur, qualite FROM mesure")
    df["ts"] = _utc(df["ts"])
    return df.sort_values(["ts", "capteur_id"], ignore_index=True)


def load_states(db: Path) -> pd.DataFrame:
    df = _read(db, "SELECT ts, zone, actionneur, action, valeur FROM etat_actionneur")
    df["ts"] = _utc(df["ts"])
    return df.sort_values("ts", ignore_index=True)


def load_alerts(db: Path) -> pd.DataFrame:
    df = _read(db, "SELECT ts, zone, niveau, source, message FROM alerte")
    df["ts"] = _utc(df["ts"])
    return df.sort_values("ts", ignore_index=True)


def load_vision(db: Path) -> pd.DataFrame:
    try:
        df = _read(db, "SELECT * FROM vision_resultat")
    except Exception:  # noqa: BLE001 - older databases have no vision table
        return pd.DataFrame(columns=["ts", "zone", "sante", "sante_conf", "classe_conf"])
    df["ts"] = _utc(df["ts"])
    return df


def load_serre(db: Path) -> dict:
    try:
        df = _read(db, "SELECT id, fuseau, lux_vers_ppfd, parametres FROM serre")
    except Exception:  # noqa: BLE001
        return {}
    if df.empty:
        return {}
    r = df.iloc[0].to_dict()
    r["parametres"] = json.loads(r["parametres"]) if r.get("parametres") else {}
    return r


def from_sim(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(measurements, states) in the long format from the wide `sim.dataset.generate` table.

    `t_ext` becomes a `t_ext` sensor in each zone; each `etat_<actuator>` column becomes
    state changes (0: off, 1: on, in between: pwm with `valeur` in %).
    """
    df = df.copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    etats = [c for c in df.columns if c.startswith("etat_")]
    sensors = [c for c in df.columns if c not in {"ts", "zone", *etats}]
    long = df.melt(id_vars=["ts", "zone"], value_vars=sensors, var_name="type",
                   value_name="valeur").dropna(subset=["valeur"])  # fmt: skip
    long["capteur_id"] = long["zone"] + "-" + long["type"]
    long["noeud"] = long["zone"]
    long["qualite"] = "ok"
    long = long[["ts", "capteur_id", "noeud", "zone", "type", "valeur", "qualite"]]
    rows = []
    for (zone, col), g in (
        df.melt(id_vars=["ts", "zone"], value_vars=etats, var_name="col")
        .sort_values("ts")
        .groupby(["zone", "col"])
    ):
        v = g["value"].to_numpy(float)
        change = np.r_[True, v[1:] != v[:-1]]
        for t, x in zip(g["ts"].to_numpy()[change], v[change], strict=True):
            action = "off" if x <= 0 else ("on" if x >= 1 else "pwm")
            rows.append((pd.Timestamp(t), zone, col.removeprefix("etat_"), action, 100 * x))
    states = pd.DataFrame(rows, columns=["ts", "zone", "actionneur", "action", "valeur"])
    return (
        long.sort_values(["ts", "capteur_id"], ignore_index=True),
        states.sort_values("ts", ignore_index=True),
    )


@dataclass
class Source:
    nom: str
    mesures: pd.DataFrame
    etats: pd.DataFrame
    alertes: pd.DataFrame = field(default_factory=pd.DataFrame)
    vision: pd.DataFrame = field(default_factory=pd.DataFrame)
    serre: dict = field(default_factory=dict)


def ensure_scenario(nom: str, scenarios_dir: Path = SCENARIOS_DIR) -> Path:
    """`data/scenarios/<nom>/serre.db`, frozen first (`sim --scenario <nom> --figer`) if absent."""
    db = Path(scenarios_dir) / nom / "serre.db"
    if not db.exists():
        from .figer import figer
        from .scenario import Scenario

        figer(Scenario.load(nom), db.parent)
    return db


def load_source(
    source: str, sim_days: int = 30, sim_seed: int = 0, scenarios_dir: Path = SCENARIOS_DIR
) -> Source:
    """`scenario:<nom>`, `sim` (generated, 10 min step) or the path of a SQLite database."""
    if source == "sim":
        from .dataset import generate

        mesures, etats = from_sim(generate(days=sim_days, seed=sim_seed))
        return Source("sim", mesures, etats, serre={"lux_vers_ppfd": LUX_VERS_PPFD})
    if source.startswith("scenario:"):
        db = ensure_scenario(source.partition(":")[2], scenarios_dir)
    else:
        db = Path(source)
        if not db.exists():
            raise FileNotFoundError(db)
    return Source(source, load_long(db), load_states(db), load_alerts(db), load_vision(db),
                  load_serre(db))  # fmt: skip


def wide(long: pd.DataFrame, freq: str = "10min") -> pd.DataFrame:
    """Mean per (zone, type) and `freq` bin (several soil probes are averaged)."""
    w = long.assign(ts=long["ts"].dt.floor(freq)).pivot_table(
        index="ts", columns=["zone", "type"], values="valeur", aggfunc="mean"
    )
    return w.asfreq(freq)


# --------------------------------------------------------------- coverage and quality


def coverage(long: pd.DataFrame, gap_factor: float = GAP_FACTOR) -> pd.DataFrame:
    """Per sensor: period, readings, median cadence, gaps (interval > gap_factor × cadence)."""
    rows = {}
    for cid, g in long.groupby("capteur_id"):
        ts = g["ts"].sort_values()
        d = ts.diff().dt.total_seconds().dropna()
        cadence = float(d.median()) if len(d) else float("nan")
        gaps = d[d > gap_factor * cadence] if len(d) else d
        rows[cid] = {
            "zone": g["zone"].iloc[0],
            "type": g["type"].iloc[0],
            "debut": ts.iloc[0],
            "fin": ts.iloc[-1],
            "n": int(len(g)),
            "cadence_s": cadence,
            "n_trous": int(len(gaps)),
            "duree_trous_s": float(gaps.sum()),
            "trou_max_s": float(gaps.max()) if len(gaps) else 0.0,
        }
    return pd.DataFrame(rows).T.sort_values(["zone", "type"])


def gaps(long: pd.DataFrame, gap_factor: float = GAP_FACTOR) -> pd.DataFrame:
    """One row per gap: sensor, start, end, duration."""
    out = []
    for cid, g in long.groupby("capteur_id"):
        ts = g["ts"].sort_values().reset_index(drop=True)
        d = ts.diff().dt.total_seconds()
        cadence = d.median()
        for i in np.flatnonzero(d > gap_factor * cadence):
            out.append((cid, ts[i - 1], ts[i], float(d[i])))
    return pd.DataFrame(out, columns=["capteur_id", "debut", "fin", "duree_s"])


def quality_share(long: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    """(share of each `qualite` per type, True if every reading is `ok`).

    A scenario with only `ok` says nothing about the absence of defects: inject faults."""
    t = pd.crosstab([long["zone"], long["type"]], long["qualite"], normalize="index")
    return t, bool((long["qualite"] == "ok").all())


# -------------------------------------------------------------------------- distributions


def summaries(long: pd.DataFrame) -> pd.DataFrame:
    q = [0.0, 0.05, 0.25, 0.5, 0.75, 0.95, 1.0]
    names = ["min", "q05", "q25", "mediane", "q75", "q95", "max"]
    s = long.groupby(["zone", "type"])["valeur"].quantile(q).unstack()
    s.columns = names
    s.insert(0, "n", long.groupby(["zone", "type"]).size())
    return s


def out_of_bounds(
    long: pd.DataFrame, bounds: dict[str, tuple[float, float]] = PHYSICAL_BOUNDS
) -> pd.DataFrame:
    lo = long["type"].map({k: v[0] for k, v in bounds.items()})
    hi = long["type"].map({k: v[1] for k, v in bounds.items()})
    bad = (long["valeur"] < lo) | (long["valeur"] > hi)
    return long[bad].assign(borne_min=lo[bad], borne_max=hi[bad])


def saturation(long: pd.DataFrame, limits: dict[str, float] = SATURATION) -> pd.DataFrame:
    """Share of readings at the top of the sensor range, per (zone, type)."""
    lim = long["type"].map(limits)
    sub = long[lim.notna()]
    sat = sub["valeur"] >= lim[lim.notna()]
    return (
        sat.groupby([sub["zone"], sub["type"]])
        .agg(["sum", "mean"])
        .rename(columns={"sum": "n_satures", "mean": "part"})
    )


def robust_outliers(
    long: pd.DataFrame,
    window: str = "1h",
    z: float = 5.0,
    mad_floor: float = 0.01,
    exclude: Sequence[str] = NO_OUTLIER,
) -> pd.DataFrame:
    """Readings with a robust z-score |0.6745 (x - med) / MAD| > z, median and MAD over a
    centered sliding `window` per sensor. The MAD is floored at `mad_floor` × the sensor's
    global IQR, so that a flat quantized stretch does not flag every small step."""
    out = []
    for _, g in long[~long["type"].isin(exclude)].groupby("capteur_id"):
        s = g.set_index("ts")["valeur"].sort_index()
        med = s.rolling(window, center=True, min_periods=3).median()
        mad = (s - med).abs().rolling(window, center=True, min_periods=3).median()
        q1, q3 = s.quantile([0.25, 0.75])
        mad = mad.clip(lower=max(mad_floor * (q3 - q1), 1e-9))
        score = 0.6745 * (s - med) / mad
        hit = score.abs() > z
        if hit.any():
            r = g.set_index("ts").sort_index()[hit.to_numpy()].reset_index()
            r["z"] = score[hit].to_numpy()
            out.append(r)
    cols = [*long.columns, "z"]
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=cols)


# ---------------------------------------------------------------------- time dynamics


def daily_profile(
    long: pd.DataFrame, types: Sequence[str], tz: str = "Europe/Paris"
) -> pd.DataFrame:
    """Median and IQR per local hour, per (zone, type)."""
    sub = long[long["type"].isin(types)]
    hour = sub["ts"].dt.tz_convert(tz).dt.hour.rename("heure")
    g = sub.groupby([sub["zone"], sub["type"], hour])["valeur"]
    return pd.DataFrame({"q25": g.quantile(0.25), "mediane": g.median(), "q75": g.quantile(0.75)})


def dli(
    long: pd.DataFrame,
    lux_vers_ppfd: float = LUX_VERS_PPFD,
    tz: str = "Europe/Paris",
    max_gap_s: float = 900.0,
) -> pd.DataFrame:
    """Daily light integral (mol/m²/day) per zone and local day, by trapezoids between lux
    readings (× lux_vers_ppfd -> µmol/m²/s), intervals longer than `max_gap_s` skipped;
    same conversion as the greenhouse (`backend.consumption.light_integral`)."""
    sub = long[long["type"] == "lux"]
    rows = []
    for zone, g in sub.groupby("zone"):
        s = g.groupby("ts")["valeur"].mean().sort_index()
        t = s.index
        dt = np.diff(t).astype("timedelta64[ns]").astype(np.int64) / 1e9
        mean = (s.to_numpy()[1:] + s.to_numpy()[:-1]) / 2
        ok = dt <= max_gap_s
        day = t[:-1].tz_convert(tz).date
        part = pd.DataFrame({"jour": day, "integ": np.where(ok, mean * dt, 0.0),
                             "couvert_s": np.where(ok, dt, 0.0)})  # fmt: skip
        agg = part.groupby("jour").sum()
        for jour, r in agg.iterrows():
            rows.append((zone, jour, r["integ"] * lux_vers_ppfd / 1e6, r["couvert_s"] / 3600))
    return pd.DataFrame(rows, columns=["zone", "jour", "dli", "couverture_h"])


def acf(series: pd.Series, nlags: int) -> np.ndarray:
    """Autocorrelation at lags 0..nlags of a regular series (gaps interpolated)."""
    x = series.interpolate(limit_direction="both").to_numpy(float)
    x = x - x.mean()
    denom = (x * x).sum()
    if denom == 0:
        return np.r_[1.0, np.zeros(nlags)]
    return np.array([(x[: len(x) - k] * x[k:]).sum() / denom for k in range(nlags + 1)])


def autocorrelations(w: pd.DataFrame, max_lag: str = "24h") -> pd.DataFrame:
    """ACF of each column of a regular wide table; index: lag in hours."""
    step = pd.Timedelta(w.index.freq or (w.index[1] - w.index[0]))
    nlags = min(int(pd.Timedelta(max_lag) / step), len(w) - 2)
    data = {c: acf(w[c], nlags) for c in w.columns if w[c].notna().sum() > nlags}
    out = pd.DataFrame(data, index=np.arange(nlags + 1) * step / pd.Timedelta("1h"))
    out.index.name = "lag_h"
    return out


def useful_horizon(acfs: pd.DataFrame, thresh: float = 0.5) -> pd.Series:
    """First lag (h) where the ACF falls below `thresh`: beyond, persistence says little."""
    below = acfs.lt(thresh)
    return below.idxmax().where(below.any())


def decompose(series: pd.Series, period: str = "1D") -> tuple[pd.DataFrame, dict]:
    """Trend (centered moving mean over `period`) + mean daily profile + residual.

    Returns the components and the share of variance of the profile and of the residual."""
    s = series.interpolate(limit_direction="both")
    trend = s.rolling(period, center=True, min_periods=1).mean()
    detr = s - trend
    tod = s.index.hour * 60 + s.index.minute
    seasonal = detr.groupby(tod).transform("mean")
    resid = s - trend - seasonal
    var = s.var()
    parts = {
        "part_journalier": float(seasonal.var() / var) if var > 0 else None,
        "part_residu": float(resid.var() / var) if var > 0 else None,
    }
    comps = pd.DataFrame({"serie": s, "tendance": trend, "journalier": seasonal, "residu": resid})
    return comps, parts


def correlations(w: pd.DataFrame, zone: str) -> pd.DataFrame:
    """Pearson correlations between the sensors of a zone (with `t_ext` for `sim`)."""
    sub = w[zone] if zone in w.columns.get_level_values(0) else w
    sub = sub.loc[:, sub.std() > 0]
    return sub.corr()


# ------------------------------------------------------------- actuators, alerts, vision


def _is_active(states: pd.DataFrame) -> pd.Series:
    return states["action"].isin(ACTIVE) & ~(
        (states["action"] == "pwm") & (states["valeur"].fillna(1) <= 0)
    )


def duty_cycles(
    states: pd.DataFrame, end: pd.Timestamp | None = None, start: pd.Timestamp | None = None
) -> pd.DataFrame:
    """Per (zone, actuator): share of active time over [start, end], number and durations of
    the active cycles. Default start: first state of the actuator; end: last state overall."""
    end = end if end is not None else states["ts"].max()
    rows = {}
    for (zone, act), g in states.groupby(["zone", "actionneur"]):
        g = g.sort_values("ts")
        t = list(g["ts"])
        a = list(_is_active(g))
        t0 = start if start is not None else t[0]
        on_s, cycles, cur = 0.0, [], None
        for i, (ti, ai) in enumerate(zip(t, a, strict=True)):
            t_next = t[i + 1] if i + 1 < len(t) else end
            if ai:
                on_s += max(0.0, (min(t_next, end) - max(ti, t0)).total_seconds())
                if cur is None:
                    cur = ti
            elif cur is not None:
                cycles.append((ti - cur).total_seconds())
                cur = None
        if cur is not None:
            cycles.append((end - cur).total_seconds())
        total = (end - t0).total_seconds()
        rows[(zone, act)] = {
            "taux_activation": on_s / total if total > 0 else None,
            "n_cycles": len(cycles),
            "duree_mediane_s": float(np.median(cycles)) if cycles else None,
            "duree_max_s": float(max(cycles)) if cycles else None,
        }
    out = pd.DataFrame(rows).T
    out.index.names = ["zone", "actionneur"]
    return out


def state_series(states: pd.DataFrame, zone: str, act: str, index: pd.DatetimeIndex):
    """Actuator state (0..1) sampled on `index` (step function, 0 before the first state)."""
    g = states[(states["zone"] == zone) & (states["actionneur"] == act)].sort_values("ts")
    if g.empty:
        return pd.Series(0.0, index=index)
    v = np.where(_is_active(g), np.where(g["action"] == "pwm", g["valeur"].fillna(100) / 100,
                                         1.0), 0.0)  # fmt: skip
    s = pd.Series(v, index=pd.DatetimeIndex(g["ts"])).groupby(level=0).last()
    return s.reindex(index.union(s.index)).ffill().reindex(index).fillna(0.0)


def cross_correlation(x: pd.Series, y: pd.Series, max_lag: int) -> pd.Series:
    """corr(x(t), y(t + k)) for k = 0..max_lag (steps): y lags x by the argmax."""
    return pd.Series({k: x.corr(y.shift(-k)) for k in range(max_lag + 1)})


def lag_effect(
    states: pd.DataFrame,
    long: pd.DataFrame,
    pairs: Sequence[tuple[str, str]] = DEFAULT_PAIRS,
    freq: str = "1min",
    max_lag: str = "2h",
) -> pd.DataFrame:
    """Delay command -> effect: cross-correlation between an actuator state and the
    derivative of the sensor it acts on; lag (min) and value of the strongest |corr|."""
    w = wide(long, freq).interpolate(limit=30)
    nlag = int(pd.Timedelta(max_lag) / pd.Timedelta(freq))
    rows = []
    for zone in sorted(states["zone"].unique()):
        for act, typ in pairs:
            if (zone, typ) not in w.columns:
                continue
            st = state_series(states, zone, act, w.index)
            if st.std() == 0:
                continue
            xc = cross_correlation(st, w[(zone, typ)].diff(), nlag)
            if xc.isna().all():
                continue
            k = int(xc.abs().idxmax())
            rows.append({"zone": zone, "actionneur": act, "capteur": typ,
                         "lag_min": k * pd.Timedelta(freq) / pd.Timedelta("1min"),
                         "corr": float(xc[k])})  # fmt: skip
    return pd.DataFrame(rows, columns=["zone", "actionneur", "capteur", "lag_min", "corr"])


def alerts_summary(alerts: pd.DataFrame) -> dict:
    if alerts.empty:
        return {"n": 0}
    return {
        "n": int(len(alerts)),
        "niveau_zone": pd.crosstab(alerts["niveau"], alerts["zone"]),
        "par_source": alerts["source"].value_counts(),
    }


def vision_summary(vision: pd.DataFrame) -> dict:
    if vision.empty:
        return {"n": 0}
    return {
        "n": int(len(vision)),
        "par_zone": vision["zone"].value_counts(),
        "sante": pd.crosstab(vision["zone"], vision["sante"]),
        "confiances": vision[["espece_conf", "sante_conf", "classe_conf"]].describe()
        if "espece_conf" in vision
        else vision[["sante_conf"]].describe(),
    }


# ------------------------------------------------------------------------------ faults


def inject_faults(long: pd.DataFrame, specs: Sequence[str]) -> pd.DataFrame:
    """Applies `sim.faults` specs (`fige:z1/temperature@30-90`, `aberrant:…`,
    `valeur:…`, `deconnexion:<noeud>@…`), minutes from the first reading, to the
    measurements: to check that coverage, outliers and bounds reveal them (§5.1)."""
    from .faults import Faults, parse_fault

    if not specs:
        return long
    df = long.sort_values("ts", ignore_index=True)
    t0 = df["ts"].min().to_pydatetime()
    faults = Faults([parse_fault(s, t0) for s in specs])
    keep, values = [], []
    for r in df.itertuples():
        t = r.ts.to_pydatetime()
        keep.append(not faults.disconnected(r.noeud, t))
        values.append(faults.apply(r.zone, r.type, r.valeur, t))
    return df.assign(valeur=values)[keep].reset_index(drop=True)
