"""Plots of the sensor statistics (docs/19 §5), called by the notebook 08 only.

Each `plot_*` takes the output of a `sim.stats` function, returns the matplotlib figure and
saves it as PNG when `path` is given.
"""

from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.figure import Figure


def _save(fig: Figure, path: Path | None) -> Figure:
    fig.tight_layout()
    if path is not None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=120)
    return fig


def _grid(n: int, cols: int = 4, size=(3.4, 2.8)):
    rows = max(1, -(-n // cols))
    fig = Figure(figsize=(cols * size[0], rows * size[1]))
    axes = np.atleast_1d(fig.subplots(rows, cols)).ravel()
    for ax in axes[n:]:
        ax.axis("off")
    return fig, axes


def plot_timeline(long: pd.DataFrame, gaps: pd.DataFrame | None = None, path=None) -> Figure:
    """One line per sensor: readings over time, gaps in red."""
    ids = sorted(long["capteur_id"].unique())
    fig = Figure(figsize=(12, 0.3 * len(ids) + 1.2))
    ax = fig.subplots()
    for k, cid in enumerate(ids):
        ts = long.loc[long["capteur_id"] == cid, "ts"]
        ax.plot([ts.min(), ts.max()], [k, k], color="C0", lw=4, solid_capstyle="butt")
        if gaps is not None:
            for r in gaps[gaps["capteur_id"] == cid].itertuples():
                ax.plot([r.debut, r.fin], [k, k], color="C3", lw=6, solid_capstyle="butt")
    ax.set_yticks(range(len(ids)), ids, fontsize=7)
    ax.set_title("couverture (rouge : trous)")
    return _save(fig, path)


def plot_histograms(long: pd.DataFrame, path=None) -> Figure:
    keys = sorted(long.groupby(["zone", "type"]).groups)
    fig, axes = _grid(len(keys))
    for ax, (zone, typ) in zip(axes, keys, strict=False):
        v = long.loc[(long["zone"] == zone) & (long["type"] == typ), "valeur"]
        ax.hist(v, bins=50, color="C0")
        ax.set_title(f"{zone} {typ}", fontsize=8)
    return _save(fig, path)


def plot_daily_profiles(profile: pd.DataFrame, path=None) -> Figure:
    keys = sorted({k[:2] for k in profile.index})
    fig, axes = _grid(len(keys))
    for ax, key in zip(axes, keys, strict=False):
        p = profile.loc[key]
        ax.plot(p.index, p["mediane"], color="C0")
        ax.fill_between(p.index, p["q25"], p["q75"], color="C0", alpha=0.3)
        ax.set_title(f"{key[0]} {key[1]}", fontsize=8)
        ax.set_xlabel("heure locale")
        ax.set_xticks(range(0, 24, 6))
    return _save(fig, path)


def plot_acf(acfs: pd.DataFrame, thresh: float = 0.5, path=None) -> Figure:
    fig = Figure(figsize=(8, 4))
    ax = fig.subplots()
    for c in acfs.columns:
        label = " ".join(c) if isinstance(c, tuple) else str(c)
        ax.plot(acfs.index, acfs[c], label=label, lw=1)
    ax.axhline(thresh, color="k", ls="--", lw=0.8)
    ax.set_xlabel("décalage (h)")
    ax.set_ylabel("autocorrélation")
    ax.legend(fontsize=6, ncol=2)
    return _save(fig, path)


def plot_decomposition(comps: pd.DataFrame, title: str = "", path=None) -> Figure:
    fig = Figure(figsize=(10, 6))
    axes = fig.subplots(len(comps.columns), 1, sharex=True)
    for ax, c in zip(axes, comps.columns, strict=True):
        ax.plot(comps.index, comps[c], lw=0.8)
        ax.set_ylabel(c, fontsize=8)
    axes[0].set_title(title)
    return _save(fig, path)


def plot_corr(corr: pd.DataFrame, title: str = "", path=None) -> Figure:
    fig = Figure(figsize=(5.5, 4.8))
    ax = fig.subplots()
    im = ax.imshow(corr.to_numpy(), vmin=-1, vmax=1, cmap="RdBu_r")
    labels = [" ".join(c) if isinstance(c, tuple) else str(c) for c in corr.columns]
    ax.set_xticks(range(len(labels)), labels, rotation=90, fontsize=7)
    ax.set_yticks(range(len(labels)), labels, fontsize=7)
    fig.colorbar(im, ax=ax)
    ax.set_title(title)
    return _save(fig, path)


def plot_states(states: pd.DataFrame, end=None, path=None) -> Figure:
    """Gantt of the active periods per (zone, actuator)."""
    from .stats import _is_active

    end = end if end is not None else states["ts"].max()
    keys = sorted(states.groupby(["zone", "actionneur"]).groups)
    fig = Figure(figsize=(12, 0.32 * len(keys) + 1.2))
    ax = fig.subplots()
    for k, (zone, act) in enumerate(keys):
        g = states[(states["zone"] == zone) & (states["actionneur"] == act)].sort_values("ts")
        t = list(g["ts"]) + [end]
        for i, a in enumerate(_is_active(g)):
            if a:
                ax.plot([t[i], t[i + 1]], [k, k], color="C2", lw=6, solid_capstyle="butt")
    ax.set_yticks(range(len(keys)), [f"{z} {a}" for z, a in keys], fontsize=7)
    ax.set_title("actionneurs actifs")
    return _save(fig, path)


def plot_alerts(alerts: pd.DataFrame, path=None) -> Figure:
    levels = ["info", "warning", "critique"]
    fig = Figure(figsize=(12, 2.6))
    ax = fig.subplots()
    for k, lvl in enumerate(levels):
        t = alerts.loc[alerts["niveau"] == lvl, "ts"]
        ax.scatter(t, np.full(len(t), k), color=f"C{k}", s=18, label=lvl)
    others = alerts[~alerts["niveau"].isin(levels)]
    if len(others):
        ax.scatter(others["ts"], np.full(len(others), len(levels)), color="k", s=18)
    ax.set_yticks(range(len(levels)), levels)
    ax.set_title("alertes")
    return _save(fig, path)


def plot_series(
    w: pd.DataFrame, cols: Sequence[tuple[str, str]], title: str = "", path=None
) -> Figure:
    fig = Figure(figsize=(12, 3.2))
    ax = fig.subplots()
    for c in cols:
        if c in w.columns:
            ax.plot(w.index, w[c], lw=0.8, label=" ".join(c))
    ax.legend(fontsize=7)
    ax.set_title(title)
    return _save(fig, path)
