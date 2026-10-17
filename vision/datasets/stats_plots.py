"""Plots of the dataset statistics (docs/19 §2), called by the notebooks 06 and 07 only.

Each `plot_*` takes the output of a `vision.datasets.stats` function, returns the matplotlib
figure and saves it as PNG when `path` is given.
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


def _colors(keys: Sequence[str]) -> dict[str, tuple]:
    from matplotlib import colormaps

    cmap = colormaps["tab10"]
    return {k: cmap(i % 10) for i, k in enumerate(sorted(set(keys)))}


def plot_long_tail(tail: pd.DataFrame, path: Path | None = None) -> Figure:
    """Count per classe (descending, log scale), colored by majority source."""
    colors = _colors(tail["source_majoritaire"])
    fig = Figure(figsize=(12, 4))
    ax = fig.subplots()
    x = np.arange(len(tail))
    ax.bar(x, tail["n"], color=[colors[s] for s in tail["source_majoritaire"]], width=0.9)
    ax.set_yscale("log")
    ax.set_xticks(x, [c.split("/", 1)[1] for c in tail.index], rotation=90, fontsize=6)
    ax.set_ylabel("images (log)")
    for s, c in colors.items():
        ax.bar([], [], color=c, label=s)
    ax.legend(title="source majoritaire")
    return _save(fig, path)


def plot_distributions(
    table: pd.DataFrame, cols: Sequence[str], by: str = "source", path: Path | None = None,
    log: Sequence[str] = ("nettete",),
) -> Figure:  # fmt: skip
    """Box plots of each column per `by` group."""
    groups = sorted(table[by].astype(str).unique())
    fig = Figure(figsize=(3.2 * len(cols), 3.4))
    axes = np.atleast_1d(fig.subplots(1, len(cols)))
    for ax, c in zip(axes, cols, strict=True):
        data = [table.loc[table[by].astype(str) == g, c].dropna().to_numpy() for g in groups]
        ax.boxplot(data, tick_labels=groups, showfliers=False)
        ax.set_title(c)
        ax.tick_params(axis="x", rotation=45, labelsize=7)
        if c in log:
            ax.set_yscale("log")
    return _save(fig, path)


def plot_pca(proj: pd.DataFrame, by: str = "source", path: Path | None = None) -> Figure:
    colors = _colors(proj[by].astype(str))
    fig = Figure(figsize=(6, 5))
    ax = fig.subplots()
    for g, sub in proj.groupby(proj[by].astype(str)):
        ax.scatter(sub["pc1"], sub["pc2"], s=4, alpha=0.5, color=colors[g], label=g)
    var = proj.attrs.get("variance", [None, None])
    ax.set_xlabel(f"PC1 ({var[0]:.0%})" if var[0] is not None else "PC1")
    ax.set_ylabel(f"PC2 ({var[1]:.0%})" if var[1] is not None else "PC2")
    ax.legend(markerscale=3)
    return _save(fig, path)


def plot_hash_distances(pairs: pd.DataFrame, threshold: int = 8, path: Path | None = None):
    """Histograms of the pHash and dHash distances of the candidate pairs."""
    fig = Figure(figsize=(10, 3.4))
    a1, a2 = fig.subplots(1, 2)
    a1.hist(pairs["d_phash"], bins=np.arange(-0.5, pairs["d_phash"].max() + 1.5), color="C0")
    a1.set_title("pHash (paires candidates)")
    a2.hist(pairs["d_dhash"], bins=np.arange(-0.5, 65.5), color="C1")
    a2.axvline(threshold + 0.5, color="k", ls="--", label=f"seuil dHash ≤ {threshold}")
    a2.set_title("dHash")
    a2.legend()
    for ax in (a1, a2):
        ax.set_xlabel("distance de Hamming")
        ax.set_yscale("log")
    return _save(fig, path)


def plot_image_grid(
    paths: Sequence[Path], titles: Sequence[str] | None = None, cols: int = 6,
    path: Path | None = None, boxes: Sequence[Sequence] | None = None,
) -> Figure:  # fmt: skip
    """Sheet of images (optionally with pixel boxes x0 y0 x1 y1 drawn)."""
    from vision.datasets.dataset import read_rgb
    from vision.labeling.build_yolo_dataset import draw_boxes

    n = max(1, len(paths))
    rows = -(-n // cols)
    fig = Figure(figsize=(cols * 2.4, rows * 2.6))
    axes = np.atleast_1d(fig.subplots(rows, cols)).ravel()
    for ax in axes:
        ax.axis("off")
    for k, (ax, p) in enumerate(zip(axes, paths, strict=False)):
        img = read_rgb(Path(p))
        if boxes is not None:
            img = draw_boxes(img, boxes[k])
        ax.imshow(img)
        if titles is not None:
            ax.set_title(titles[k], fontsize=6)
    return _save(fig, path)


def plot_yolo_examples(
    yolo_dir: Path, manifest: pd.DataFrame, boxes: pd.DataFrame, n: int, seed: int = 0,
    path: Path | None = None,
) -> Figure:  # fmt: skip
    """n images of the manifest rows with their boxes, titled source (n boxes)."""
    sub = manifest.sample(min(n, len(manifest)), random_state=seed)
    paths, titles, all_boxes = [], [], []
    for r in sub.itertuples():
        b = boxes[boxes["image"] == r.image]
        xy = np.stack([(b["xc"] - b["w"] / 2) * r.width, (b["yc"] - b["h"] / 2) * r.height,
                       (b["xc"] + b["w"] / 2) * r.width, (b["yc"] + b["h"] / 2) * r.height],
                      axis=1) if len(b) else np.empty((0, 4))  # fmt: skip
        paths.append(Path(yolo_dir) / r.image)
        titles.append(f"{r.source} ({len(b)})")
        all_boxes.append(xy)
    return plot_image_grid(paths, titles, cols=4, path=path, boxes=all_boxes)


def plot_box_geometry(geom: pd.DataFrame, path: Path | None = None) -> Figure:
    """Relative area, aspect and boxes per image, per source."""
    fig = Figure(figsize=(12, 3.4))
    a1, a2, a3 = fig.subplots(1, 3)
    for s, sub in geom.groupby("source"):
        a1.hist(sub["aire_rel"], bins=np.logspace(-5, 0, 40), alpha=0.6, label=s)
        a2.hist(np.log2(sub["aspect"].dropna()), bins=40, alpha=0.6, label=s)
        n = sub.groupby("image").size()
        a3.hist(n, bins=np.arange(0.5, n.max() + 1.5), alpha=0.6, label=s)
    a1.set_xscale("log")
    a1.set_title("aire relative")
    a2.set_title("log2(largeur / hauteur)")
    a3.set_title("boîtes par image")
    for ax in (a1, a2, a3):
        ax.legend(fontsize=7)
    return _save(fig, path)


def plot_heatmaps(maps: dict[str, np.ndarray], path: Path | None = None) -> Figure:
    """Box-center heatmaps (one per key, e.g. per source)."""
    fig = Figure(figsize=(3.6 * len(maps), 3.4))
    axes = np.atleast_1d(fig.subplots(1, len(maps)))
    for ax, (k, m) in zip(axes, maps.items(), strict=True):
        ax.imshow(m, extent=(0, 1, 1, 0), cmap="magma")
        ax.set_title(f"centres : {k}")
    return _save(fig, path)


def plot_embedding(
    xy: np.ndarray, labels: Sequence[str], title: str, path: Path | None = None
) -> Figure:
    labels = [str(v) for v in labels]
    colors = _colors(labels)
    fig = Figure(figsize=(6, 5))
    ax = fig.subplots()
    lab = np.array(labels)
    for g, c in colors.items():
        m = lab == g
        ax.scatter(xy[m, 0], xy[m, 1], s=3, alpha=0.5, color=c, label=g)
    ax.set_title(title)
    if len(colors) <= 12:
        ax.legend(markerscale=3, fontsize=7)
    return _save(fig, path)
