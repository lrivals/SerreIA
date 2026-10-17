"""Sensor series statistics (docs/19 §5) on a temporary SQLite database and fake series."""

import sqlite3
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from sim import stats as ss

T0 = datetime(2026, 7, 14, 0, 0, tzinfo=UTC)


def _ts(seconds: float) -> str:
    return (T0 + timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M:%S.%f")


@pytest.fixture
def db(tmp_path):
    """z1 humidite every 30 s for 1 h with a 300 s gap and one 120 % reading; z1
    temperature regular; ventilo on 0–10 min and 30–40 min; two alerts."""
    path = tmp_path / "serre.db"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE mesure (ts DATETIME, capteur_id TEXT, zone TEXT, type TEXT, noeud TEXT,
            emplacement TEXT, valeur FLOAT, unite TEXT, qualite TEXT);
        CREATE TABLE etat_actionneur (ts DATETIME, zone TEXT, actionneur TEXT,
            actionneur_id TEXT, action TEXT, valeur FLOAT);
        CREATE TABLE alerte (ts DATETIME, id TEXT, zone TEXT, niveau TEXT, message TEXT,
            source TEXT, acquittee BOOLEAN);
        CREATE TABLE serre (id TEXT, nom TEXT, fuseau TEXT, tarif_kwh FLOAT,
            lux_vers_ppfd FLOAT, config_version INT, parametres JSON);
    """)
    rows = []
    for k in range(121):
        t = 30 * k
        rows.append((_ts(t), "n1-temperature", "z1", "temperature", "n1", None, 20.0, "°C", "ok"))
        if 600 < t < 900:  # gap: 600 -> 900 (300 s)
            continue
        v = 120.0 if t == 1500 else 60.0
        rows.append((_ts(t), "n1-humidite", "z1", "humidite", "n1", None, v, "%", "ok"))
    con.executemany("INSERT INTO mesure VALUES (?,?,?,?,?,?,?,?,?)", rows)
    con.executemany(
        "INSERT INTO etat_actionneur VALUES (?,?,?,?,?,?)",
        [
            (_ts(0), "z1", "ventilo", "v", "pwm", 100.0),
            (_ts(600), "z1", "ventilo", "v", "off", None),
            (_ts(1800), "z1", "ventilo", "v", "on", None),
            (_ts(2400), "z1", "ventilo", "v", "off", None),
            (_ts(3600), "z1", "chauffage", "c", "off", None),
        ],
    )
    con.executemany(
        "INSERT INTO alerte VALUES (?,?,?,?,?,?,?)",
        [(_ts(100), "a", "z1", "warning", "m", "controller", 0),
         (_ts(200), "b", "z1", "info", "m", "controller", 0)],
    )  # fmt: skip
    con.execute("INSERT INTO serre VALUES ('maison','M','Europe/Paris',0.25,0.0185,1,'{\"a\": 1}')")
    con.commit()
    con.close()
    return path


def test_load_and_coverage(db):
    src = ss.load_source(str(db))
    long = src.mesures
    assert str(long["ts"].dt.tz) == "UTC" and len(long) == 121 + 112
    assert src.serre["fuseau"] == "Europe/Paris" and src.serre["parametres"] == {"a": 1}
    cov = ss.coverage(long, gap_factor=2)
    hr = cov.loc["n1-humidite"]
    assert hr["cadence_s"] == 30 and hr["n_trous"] == 1 and hr["duree_trous_s"] == 300
    assert cov.loc["n1-temperature", "n_trous"] == 0
    g = ss.gaps(long)
    assert len(g) == 1 and g.iloc[0]["duree_s"] == 300
    share, only_ok = ss.quality_share(long)
    assert only_ok and share["ok"].eq(1).all()


def test_bounds_summaries_outliers(db):
    long = ss.load_long(db)
    oob = ss.out_of_bounds(long)
    assert len(oob) == 1 and oob.iloc[0]["valeur"] == 120 and oob.iloc[0]["borne_max"] == 100
    s = ss.summaries(long)
    assert s.loc[("z1", "humidite"), "max"] == 120 and s.loc[("z1", "temperature"), "n"] == 121
    out = ss.robust_outliers(long, window="10min", z=5)
    assert out["valeur"].tolist() == [120.0]


def test_saturation():
    long = pd.DataFrame({"zone": "z1", "type": "lux", "valeur": [100.0, 65535.0, 65535.0, 0.0]})
    sat = ss.saturation(long)
    assert sat.loc[("z1", "lux"), "n_satures"] == 2 and sat.loc[("z1", "lux"), "part"] == 0.5


def test_duty_cycles(db):
    states = ss.load_states(db)
    d = ss.duty_cycles(states)
    v = d.loc[("z1", "ventilo")]
    assert v["taux_activation"] == pytest.approx(1200 / 3600)
    assert v["n_cycles"] == 2 and v["duree_mediane_s"] == 600
    assert d.loc[("z1", "chauffage"), "n_cycles"] == 0


def test_state_series(db):
    states = ss.load_states(db)
    idx = pd.date_range(T0, periods=7, freq="10min")
    s = ss.state_series(states, "z1", "ventilo", idx)
    assert s.tolist() == [1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]


def test_alerts(db):
    a = ss.alerts_summary(ss.load_alerts(db))
    assert a["n"] == 2 and a["niveau_zone"].loc["warning", "z1"] == 1
    assert ss.vision_summary(ss.load_vision(db))["n"] == 0


def test_daily_profile_local_hour():
    ts = pd.date_range(T0, periods=48, freq="1h")
    long = pd.DataFrame({"ts": ts, "zone": "z1", "type": "temperature",
                         "valeur": ts.hour.to_numpy(float)})  # fmt: skip
    p = ss.daily_profile(long, ["temperature"], tz="Europe/Paris")  # UTC+2 in July
    assert p.loc[("z1", "temperature", 2), "mediane"] == 0.0
    assert p.loc[("z1", "temperature", 14), "q25"] == 12.0


def test_dli_constant_light():
    ts = pd.date_range(datetime(2026, 7, 14, 0, tzinfo=UTC), periods=24 * 60 + 1, freq="1min")
    long = pd.DataFrame({"ts": ts, "zone": "z1", "type": "lux", "valeur": 10_000.0})
    d = ss.dli(long, lux_vers_ppfd=0.02, tz="UTC")
    day = d[d["jour"] == ts[0].date()].iloc[0]
    assert day["dli"] == pytest.approx(10_000 * 0.02 * 86400 / 1e6)
    assert day["couverture_h"] == pytest.approx(24)
    gap = long.drop(index=range(100, 200))
    assert ss.dli(gap, 0.02, tz="UTC").iloc[0]["couverture_h"] < 24


def test_acf_horizon_and_decompose():
    idx = pd.date_range(T0, periods=6 * 24 * 4, freq="10min")
    daily = np.sin(2 * np.pi * (idx.hour * 60 + idx.minute) / 1440)
    w = pd.DataFrame({("z1", "temperature"): 20 + 5 * daily}, index=idx).asfreq("10min")
    acfs = ss.autocorrelations(w, max_lag="24h")
    col = ("z1", "temperature")
    assert acfs.loc[0.0, col] == pytest.approx(1.0)
    assert acfs.loc[12.0, col] < -0.8  # half a period: anticorrelated (biased estimator)
    h = ss.useful_horizon(acfs, 0.5)
    assert 3.5 <= h[col] <= 4.5  # cos(2π h/24) = 0.5 at h = 4 (minus edge effects)
    comps, parts = ss.decompose(w[col])
    assert parts["part_journalier"] > 0.8


def test_cross_correlation_lag():
    rng = np.random.default_rng(0)
    x = pd.Series(rng.normal(size=500))
    y = x.shift(5).fillna(0)
    xc = ss.cross_correlation(x, y, 10)
    assert int(xc.idxmax()) == 5 and xc[5] == pytest.approx(1.0, abs=0.02)


def test_lag_effect_fan_cools():
    idx = pd.date_range(T0, periods=600, freq="1min")
    on = ((idx - idx[0]).total_seconds() // 3600 % 2 == 0).astype(float)  # 1 h on / 1 h off
    # temperature falls 3 min after the fan starts, rises when it stops
    slope = np.where(np.roll(on, 3) > 0, -0.05, 0.05)
    temp = 25 + np.cumsum(slope)
    long = pd.DataFrame({"ts": idx, "capteur_id": "t", "noeud": "n", "zone": "z1",
                         "type": "temperature", "valeur": temp, "qualite": "ok"})  # fmt: skip
    change = np.r_[True, on[1:] != on[:-1]]
    action = np.where(on[change] > 0, "on", "off")
    states = pd.DataFrame({"ts": idx[change], "zone": "z1", "actionneur": "ventilo",
                           "action": action, "valeur": None})  # fmt: skip
    r = ss.lag_effect(states, long, pairs=[("ventilo", "temperature")], max_lag="30min")
    row = r.iloc[0]
    assert row["lag_min"] == 3 and row["corr"] < -0.9


def test_from_sim():
    ts = pd.date_range(T0, periods=3, freq="10min")
    df = pd.DataFrame({"ts": list(ts) * 2, "zone": ["z1"] * 3 + ["z2"] * 3,
                       "temperature": [20.0, 21, 22, 18, 18, 18], "t_ext": [10.0] * 6,
                       "ph": [None] * 3 + [6.0] * 3,
                       "etat_ventilo": [0.0, 1, 1, 0, 0, 0.5]})  # fmt: skip
    long, states = ss.from_sim(df)
    assert set(long["type"]) == {"temperature", "t_ext", "ph"}
    assert len(long[long["type"] == "ph"]) == 3  # NaN dropped for z1
    assert (long["qualite"] == "ok").all()
    z1 = states[states["zone"] == "z1"]
    assert z1["action"].tolist() == ["off", "on"]
    z2 = states[states["zone"] == "z2"]
    assert z2["action"].tolist() == ["off", "pwm"] and z2.iloc[1]["valeur"] == 50.0
    w = ss.wide(long, "10min")
    assert w[("z1", "temperature")].tolist() == [20.0, 21, 22]
    corr = ss.correlations(w, "z1")
    assert "t_ext" not in corr.columns  # constant: dropped


def test_inject_faults(db):
    long = ss.load_long(db)
    f = ss.inject_faults(long, ["aberrant:z1/temperature@10", "deconnexion:n1@40-50"])
    t = f[f["type"] == "temperature"]
    assert (t["valeur"] == 60.0).sum() == 1  # 20 + 40
    assert len(f) < len(long)
    assert ss.coverage(f).loc["n1-temperature", "n_trous"] == 1
    assert ss.inject_faults(long, []) is long
