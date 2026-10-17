"""Statistics of the classifier index and of the YOLO dataset (docs/19 §2–§4).

Pure functions: a DataFrame (index rows, YOLO manifest, boxes) in, a DataFrame or a
serializable dict out, so that each one is tested on synthetic data. The plots live in
`stats_plots`, the notebooks 06 and 07 only call and display.
"""

import itertools
import logging
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from vision.datasets.build_index import MAX_HAMMING
from vision.datasets.near_duplicates import _chunks
from vision.labeling.yolo_format import box_iou, label_path, read_labels

log = logging.getLogger(__name__)

LABO_SPLITS = ("train", "val", "test")
LEVELS = ("espece", "classe", "sante")
INPUT_SIZE = 224  # classifier input (configs/clf_*.yaml data.size)
# Photometric descriptors (§3.5); teinte (hue, degrees) is circular and kept out of the PCA.
DESCRIPTORS = ("luminosite", "contraste", "saturation", "teinte", "nettete", "fond_uni")
PCA_DESCRIPTORS = ("luminosite", "contraste", "saturation", "log_nettete", "fond_uni")
COCO_SMALL, COCO_MEDIUM = 32**2, 96**2  # px² at the network input size


# ------------------------------------------------------------------ counts and imbalance


def counts(df: pd.DataFrame, rows: str, cols: str = "split") -> pd.DataFrame:
    """Crosstab rows × cols with margins (`All`)."""
    return pd.crosstab(df[rows].astype(str), df[cols].astype(str), margins=True)


def imbalance(counts: Sequence[float] | pd.Series) -> dict:
    """Imbalance of a count vector: max/min ratio, normalized entropy, Gini, effective count.

    Entropy in nats; `entropie_norm` = H / log(K) (1: uniform); `n_effectif` = exp(H), the
    number of equally frequent classes that would give the same entropy. Gini 0: uniform.
    """
    c = np.asarray(counts, dtype=np.float64)
    c = c[c > 0]
    k = len(c)
    if k == 0:
        return {"k": 0, "ratio_max_min": None, "entropie_norm": None, "gini": None,
                "n_effectif": None}  # fmt: skip
    p = c / c.sum()
    h = float(-(p * np.log(p)).sum())
    x = np.sort(c)
    gini = float(2 * (np.arange(1, k + 1) * x).sum() / (k * x.sum()) - (k + 1) / k)
    return {
        "k": k,
        "ratio_max_min": float(x[-1] / x[0]),
        "entropie_norm": h / np.log(k) if k > 1 else 1.0,
        "gini": gini,
        "n_effectif": float(np.exp(h)),
    }


def imbalance_by_level(
    df: pd.DataFrame, levels: Sequence[str] = LEVELS, split: str | None = "train"
) -> pd.DataFrame:
    """`imbalance` of each level (rows), on one split (None: every row)."""
    sub = df if split is None else df[df["split"] == split]
    return pd.DataFrame({lvl: imbalance(sub[lvl].astype(str).value_counts()) for lvl in levels}).T


def long_tail(df: pd.DataFrame) -> pd.DataFrame:
    """Count per classe, descending, with its majority source and that source's share."""
    ct = pd.crosstab(df["classe"].astype(str), df["source"].astype(str))
    out = pd.DataFrame(
        {
            "n": ct.sum(axis=1),
            "source_majoritaire": ct.idxmax(axis=1),
            "part_majoritaire": ct.max(axis=1) / ct.sum(axis=1),
        }
    )
    return out.sort_values("n", ascending=False)


# ------------------------------------------------------------------- taxonomy coverage


def coverage(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(counts, shares) classe × source; shares sum to 1 over the sources of a classe."""
    ct = pd.crosstab(df["classe"].astype(str), df["source"].astype(str))
    return ct, ct.div(ct.sum(axis=1), axis=0)


def mono_source(df: pd.DataFrame) -> pd.DataFrame:
    """Classes seen in a single source: the model may learn the source, not the symptom."""
    ct, _ = coverage(df)
    mono = ct[(ct > 0).sum(axis=1) == 1]
    return pd.DataFrame({"source": mono.idxmax(axis=1), "n": mono.sum(axis=1)}).sort_values(
        "n", ascending=False
    )


def ambiguous_weight(df: pd.DataFrame) -> dict:
    amb = df[df["ambigu"].astype(bool)]
    return {
        "classes": sorted(amb["classe"].astype(str).unique()),
        "n_images": int(len(amb)),
        "part": float(len(amb) / len(df)) if len(df) else 0.0,
        "par_classe": amb["classe"].astype(str).value_counts().to_dict(),
    }


def mask_share(df: pd.DataFrame) -> pd.Series:
    """Share of images with a `mask_path` (PlantVillage segmented/), per source."""
    has = df["mask_path"].notna() if "mask_path" in df else pd.Series(False, index=df.index)
    return has.groupby(df["source"].astype(str)).mean().rename("part_masque")


# ------------------------------------------------------------------- split consistency


def _js(p: np.ndarray, q: np.ndarray) -> float:
    """Jensen-Shannon divergence in bits (0: identical, 1: disjoint)."""
    p, q = p / p.sum(), q / q.sum()
    m = (p + q) / 2

    def kl(a, b):
        nz = a > 0
        return float((a[nz] * np.log2(a[nz] / b[nz])).sum())

    return (kl(p, m) + kl(q, m)) / 2


def split_divergence(df: pd.DataFrame, splits: Sequence[str] = LABO_SPLITS) -> dict:
    """JS divergence of the classe distribution between split pairs, χ² per source."""
    from scipy.stats import chi2_contingency

    labo = df[df["split"].isin(splits)]
    ct = pd.crosstab(labo["classe"].astype(str), labo["split"].astype(str))
    present = [s for s in splits if s in ct]
    js = {
        f"{a}/{b}": _js(ct[a].to_numpy(float), ct[b].to_numpy(float))
        for a, b in itertools.combinations(present, 2)
    }
    chi2 = {}
    for source, sub in labo.groupby(labo["source"].astype(str)):
        t = pd.crosstab(sub["classe"].astype(str), sub["split"].astype(str))
        t = t.loc[t.sum(axis=1) > 0, t.sum(axis=0) > 0]
        if t.shape[0] < 2 or t.shape[1] < 2:
            continue
        stat, p, dof, _ = chi2_contingency(t.to_numpy())
        chi2[source] = {"chi2": float(stat), "p": float(p), "ddl": int(dof)}
    return {"js": js, "chi2": chi2}


def group_leaks(df: pd.DataFrame, group_col: str = "groupe") -> pd.DataFrame:
    """Groups present in more than one split (docs/02: must be empty)."""
    g = df.dropna(subset=[group_col]).groupby(group_col)["split"]
    n = g.nunique()
    bad = n[n > 1].index
    out = (
        df[df[group_col].isin(bad)]
        .groupby(group_col)
        .agg(splits=("split", lambda s: sorted(s.astype(str).unique())), n=("split", "size"))
    )
    return out


def xdomain_gaps(df: pd.DataFrame) -> dict:
    """PlantDoc (test_xdomain) classes absent from train, and train classes absent from it."""
    train = set(df.loc[df["split"] == "train", "classe"].astype(str))
    xd = set(df.loc[df["split"] == "test_xdomain", "classe"].astype(str))
    return {"xdomain_sans_train": sorted(xd - train), "train_sans_xdomain": sorted(train - xd)}


# --------------------------------------------------------------------------- geometry


def geometry(df: pd.DataFrame, input_size: int = INPUT_SIZE) -> pd.DataFrame:
    """Per source: median / min / max width, height, aspect; share smaller than input_size."""
    g = df.assign(aspect=df["width"] / df["height"], petite=df[["width", "height"]].min(axis=1)
                  < input_size)  # fmt: skip
    by = g.groupby(g["source"].astype(str))
    out = pd.concat(
        {c: by[c].agg(["median", "min", "max"]) for c in ("width", "height", "aspect")},
        axis=1,
    )
    out[("petite", f"part<{input_size}")] = by["petite"].mean()
    return out


# ----------------------------------------------------------- near duplicates and noise


def group_sizes(df: pd.DataFrame) -> dict:
    sizes = df["groupe"].value_counts()
    return {
        "n_groupes": int(len(sizes)),
        "n_groupes_doublons": int((sizes > 1).sum()),
        "images_en_doublon": int(sizes[sizes > 1].sum()),
        "max": int(sizes.max()) if len(sizes) else 0,
        "distribution": sizes.value_counts().sort_index().to_dict(),  # size -> n groups
    }


def candidate_pair_distances(
    phash: np.ndarray, dhash: np.ndarray, max_dist: int = MAX_HAMMING
) -> pd.DataFrame:
    """Pairs within pHash distance `max_dist` (the grouping candidates) and their dHash distance.

    Same pigeonhole bucketing as `near_duplicates.group_near_duplicates`; the dHash
    histogram should be bimodal around the confirmation threshold (8).
    """
    phash = np.asarray(phash, dtype=np.uint64)
    dhash = np.asarray(dhash, dtype=np.uint64)
    n = len(phash)
    found = []
    for lo, hi in _chunks(max_dist):
        mask = np.uint64((1 << (hi - lo)) - 1)
        keys = (phash >> np.uint64(lo)) & mask
        order = np.argsort(keys, kind="stable")
        sk = keys[order]
        starts = np.flatnonzero(np.r_[True, sk[1:] != sk[:-1]])
        ends = np.r_[starts[1:], n]
        for s, e in zip(starts, ends, strict=True):
            if e - s < 2:
                continue
            idx = order[s:e]
            h = phash[idx]
            for b in range(0, len(h), 2048):
                close = np.bitwise_count(h[b : b + 2048, None] ^ h[None, b:]) <= max_dist
                ii, jj = np.nonzero(np.triu(close, k=1))
                i, j = idx[b + ii], idx[b + jj]
                found.append(np.stack([np.minimum(i, j), np.maximum(i, j)], axis=1))
    if not found:
        return pd.DataFrame({"i": [], "j": [], "d_phash": [], "d_dhash": []}, dtype=np.int64)
    pairs = np.unique(np.concatenate(found), axis=0)
    i, j = pairs[:, 0], pairs[:, 1]
    return pd.DataFrame(
        {
            "i": i,
            "j": j,
            "d_phash": np.bitwise_count(phash[i] ^ phash[j]).astype(np.int64),
            "d_dhash": np.bitwise_count(dhash[i] ^ dhash[j]).astype(np.int64),
        }
    )


def contradictory_groups(raw: pd.DataFrame) -> dict:
    """Near-duplicate groups carrying several classes (before `drop_contradictory_groups`).

    `paires`: class pairs and the number of groups mixing them; `groupes`: one row per group.
    """
    nc = raw.groupby("groupe")["classe"].nunique()
    bad = raw[raw["groupe"].isin(nc.index[nc > 1])]
    groups = bad.groupby("groupe").agg(
        classes=("classe", lambda s: sorted(s.astype(str).unique())),
        sources=("source", lambda s: sorted(s.astype(str).unique())),
        n=("path", "size"),
        paths=("path", list),
    )
    pairs: dict[tuple[str, str], int] = {}
    for cls in groups["classes"]:
        for a, b in itertools.combinations(cls, 2):
            pairs[(a, b)] = pairs.get((a, b), 0) + 1
    paires = pd.DataFrame(
        [(a, b, n) for (a, b), n in pairs.items()], columns=["classe_a", "classe_b", "n_groupes"]
    ).sort_values("n_groupes", ascending=False, ignore_index=True)
    return {
        "n_groupes": int(len(groups)),
        "n_images": int(len(bad)),
        "par_source": bad["source"].astype(str).value_counts().to_dict(),
        "paires": paires,
        "groupes": groups,
    }


def read_rejects(path: Path) -> pd.DataFrame:
    """`data/index_rejets.txt` (path<TAB>error) with source and class folder."""
    rows = []
    path = Path(path)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            p, _, err = line.partition("\t")
            rows.append({"path": p, "erreur": err, "source": p.split("/", 1)[0],
                         "dossier": Path(p).parent.name})  # fmt: skip
    return pd.DataFrame(rows, columns=["path", "erreur", "source", "dossier"])


# ------------------------------------------------------------------------- photometry


def photometry(img: np.ndarray, border: float = 0.05, tol: float = 12.0) -> dict:
    """Descriptors of one RGB image (uint8, or float in [0, 1]).

    - luminosite, contraste: mean and std of the luminance (0–255);
    - saturation: mean HSV saturation (0–255);
    - teinte: dominant hue in degrees (histogram weighted by saturation; None if gray);
    - nettete: variance of the Laplacian of the luminance (higher: sharper);
    - fond_uni: share of the border pixels (a `border` fraction of the short side) within
      `tol` (max over channels) of their median color: ~1 on PlantVillage's plain background.
    """
    if img.dtype != np.uint8:
        img = np.clip(np.asarray(img, np.float32) * 255 + 0.5, 0, 255).astype(np.uint8)
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY).astype(np.float64)
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    sat = hsv[..., 1].astype(np.float64)
    hist = np.bincount(hsv[..., 0].ravel(), weights=sat.ravel(), minlength=180)
    teinte = float(np.argmax(hist) * 2) if hist.sum() > 0 else None
    h, w = gray.shape
    b = max(1, round(border * min(h, w)))
    edge = np.concatenate(
        [
            img[:b].reshape(-1, 3),
            img[-b:].reshape(-1, 3),
            img[b:-b, :b].reshape(-1, 3),
            img[b:-b, -b:].reshape(-1, 3),
        ]  # fmt: skip
    ).astype(np.int16)
    med = np.median(edge, axis=0)
    fond = float((np.abs(edge - med).max(axis=1) <= tol).mean())
    return {
        "luminosite": float(gray.mean()),
        "contraste": float(gray.std()),
        "saturation": float(sat.mean()),
        "teinte": teinte,
        "nettete": float(cv2.Laplacian(gray, cv2.CV_64F).var()),
        "fond_uni": fond,
    }


def stratified_sample(
    df: pd.DataFrame, n: int, seed: int, by: Sequence[str] = ("source", "classe")
) -> pd.DataFrame:
    """About n rows, proportional to the `by` cells, at least one per cell."""
    if n >= len(df):
        return df.reset_index(drop=True)
    frac = n / len(df)
    parts = [
        g.sample(max(1, round(len(g) * frac)), random_state=seed)
        for _, g in df.groupby(list(by), observed=True)
    ]
    return pd.concat(parts).reset_index(drop=True)


def photometry_table(
    df: pd.DataFrame,
    data_dir: Path,
    n: int,
    seed: int = 0,
    read: Callable[[Path], np.ndarray] | None = None,
) -> pd.DataFrame:
    """`photometry` of a stratified sample (source × classe), with path/source/classe/split."""
    from tqdm.auto import tqdm

    if read is None:
        from vision.datasets.dataset import read_rgb as read
    sample = stratified_sample(df, n, seed)
    rows = []
    for r in tqdm(sample.itertuples(), total=len(sample), desc="photométrie"):
        try:
            d = photometry(read(Path(data_dir) / r.path))
        except OSError as e:
            log.warning("%s", e)
            continue
        rows.append({"path": r.path, "source": str(r.source), "classe": str(r.classe),
                     "split": str(r.split), **d})  # fmt: skip
    return pd.DataFrame(rows)


def photometry_images(images: Iterable[np.ndarray], **meta) -> pd.DataFrame:
    """`photometry` of in-memory images (an augmented batch after `denormalize`)."""
    return pd.DataFrame([{**meta, **photometry(im)} for im in images])


def descriptor_pca(table: pd.DataFrame, cols: Sequence[str] = PCA_DESCRIPTORS) -> pd.DataFrame:
    """2D PCA of the standardized descriptors; `attrs["variance"]`: explained ratios."""
    from sklearn.decomposition import PCA

    t = table.assign(log_nettete=np.log1p(table["nettete"]))
    t = t.dropna(subset=list(cols))
    x = t[list(cols)].to_numpy(float)
    std = x.std(axis=0)
    x = (x - x.mean(axis=0)) / np.where(std > 0, std, 1)
    pca = PCA(n_components=2).fit(x)
    out = pd.DataFrame(pca.transform(x), columns=["pc1", "pc2"], index=t.index)
    out = out.join(t[[c for c in ("source", "classe", "split") if c in t]])
    out.attrs["variance"] = pca.explained_variance_ratio_.tolist()
    return out


def domain_gap(
    table: pd.DataFrame,
    ref: Sequence[str] = ("plantvillage", "ccmt"),
    target: str = "plantdoc",
    cols: Sequence[str] = ("luminosite", "contraste", "saturation", "nettete", "fond_uni"),
    group_col: str = "source",
) -> pd.DataFrame:
    """Per descriptor: medians of ref and target, median gap in ref IQRs, and the share of
    the target outside the [p1, p99] range of the reference (what augmentations must cover)."""
    r = table[table[group_col].isin(ref)]
    t = table[table[group_col] == target]
    rows = {}
    for c in cols:
        rv, tv = r[c].dropna(), t[c].dropna()
        if rv.empty or tv.empty:
            continue
        q1, q3 = rv.quantile([0.25, 0.75])
        lo, hi = rv.quantile([0.01, 0.99])
        iqr = q3 - q1
        rows[c] = {
            "mediane_ref": float(rv.median()),
            "mediane_cible": float(tv.median()),
            "ecart_iqr": float((tv.median() - rv.median()) / iqr) if iqr > 0 else None,
            "hors_plage_ref": float(((tv < lo) | (tv > hi)).mean()),
        }
    return pd.DataFrame(rows).T


# ------------------------------------------------------------------------------- YOLO


def read_yolo_labels(yolo_dir: Path, manifest: pd.DataFrame) -> pd.DataFrame:
    """One row per box: image, split, source, width, height, cls, xc, yc, w, h (normalized)."""
    rows = []
    for r in manifest.itertuples():
        lp = label_path(Path(yolo_dir) / r.image)
        if not lp.exists():
            continue
        for cls, xc, yc, w, h in read_labels(lp):
            rows.append((r.image, r.split, r.source, r.width, r.height, int(cls), xc, yc, w, h))
    cols = ["image", "split", "source", "width", "height", "cls", "xc", "yc", "w", "h"]
    return pd.DataFrame(rows, columns=cols)


def boxes_per_image(manifest: pd.DataFrame, boxes: pd.DataFrame) -> pd.DataFrame:
    """Manifest rows with `n_lignes`: boxes read from labels/ (0 for empty images)."""
    n = boxes.groupby("image").size()
    return manifest.assign(n_lignes=manifest["image"].map(n).fillna(0).astype(int))


def yolo_counts(manifest: pd.DataFrame, boxes: pd.DataFrame, names: Sequence[str]) -> dict:
    """Images and boxes per split × source (× class), empty classes, images without box."""
    per_img = boxes_per_image(manifest, boxes)
    b = boxes.assign(classe=boxes["cls"].map(dict(enumerate(names))))
    par_classe = b.pivot_table(index=["source", "classe"], columns="split", values="image",
                               aggfunc="size", fill_value=0)  # fmt: skip
    seen = set(boxes["cls"].unique())
    return {
        "images": pd.crosstab(manifest["source"], manifest["split"], margins=True),
        "boites": pd.crosstab(boxes["source"], boxes["split"], margins=True),
        "boites_par_classe": par_classe,
        "classes_sans_annotation": [n for i, n in enumerate(names) if i not in seen],
        "images_sans_boite": per_img.loc[
            per_img["n_lignes"] == 0, ["image", "split", "source"]
        ].reset_index(drop=True),
        "n_images": int(len(manifest)),
        "n_boites": int(len(boxes)),
    }


def nboxes_consistency(manifest: pd.DataFrame, boxes: pd.DataFrame) -> pd.DataFrame:
    """Images whose manifest `n_boxes` differs from the lines of their labels file."""
    per_img = boxes_per_image(manifest, boxes)
    bad = per_img[per_img["n_boxes"] != per_img["n_lignes"]]
    return bad[["image", "split", "source", "n_boxes", "n_lignes"]].reset_index(drop=True)


def box_geometry(boxes: pd.DataFrame, img_size: int = 640) -> pd.DataFrame:
    """Boxes with their size at the network input (letterbox: long side -> img_size).

    Adds aire_rel (share of the image), w_px, h_px, aspect (w/h) and coco
    (small < 32², medium < 96², large).
    """
    scale = img_size / np.maximum(boxes["width"], boxes["height"])
    w_px = boxes["w"] * boxes["width"] * scale
    h_px = boxes["h"] * boxes["height"] * scale
    area = w_px * h_px
    coco = np.where(area < COCO_SMALL, "small", np.where(area < COCO_MEDIUM, "medium", "large"))
    return boxes.assign(
        aire_rel=boxes["w"] * boxes["h"],
        w_px=w_px,
        h_px=h_px,
        aspect=w_px / h_px.where(h_px > 0),
        coco=coco,
    )


def coco_share(geom: pd.DataFrame, by: str = "source") -> pd.DataFrame:
    """Share of small / medium / large boxes per `by` (rows sum to 1)."""
    ct = pd.crosstab(geom[by], geom["coco"], normalize="index")
    return ct.reindex(columns=["small", "medium", "large"], fill_value=0.0)


def center_heatmap(boxes: pd.DataFrame, bins: int = 20) -> np.ndarray:
    """(bins, bins) histogram of the box centers, rows = y (top first), normalized to 1."""
    h, _, _ = np.histogram2d(boxes["yc"], boxes["xc"], bins=bins, range=[[0, 1], [0, 1]])
    return h / h.sum() if h.sum() else h


def _xyxy(b: pd.DataFrame) -> np.ndarray:
    return np.stack(
        [b["xc"] - b["w"] / 2, b["yc"] - b["h"] / 2, b["xc"] + b["w"] / 2, b["yc"] + b["h"] / 2],
        axis=1,
    )


def box_quality(
    boxes: pd.DataFrame,
    img_size: int = 640,
    dup_iou: float = 0.9,
    min_px: float = 2.0,
    nested_frac: float = 0.95,
) -> dict[str, pd.DataFrame]:
    """Annotation problems: duplicates (IoU > dup_iou), nested boxes (≥ nested_frac of the
    smaller one inside the other, not a duplicate), degenerate (w or h < min_px at
    img_size), boxes overflowing the image."""
    geom = box_geometry(boxes, img_size)
    dups, nested = [], []
    for image, g in geom.groupby("image"):
        if len(g) < 2:
            continue
        xy = _xyxy(g)
        iou = box_iou(xy, xy)
        area = (xy[:, 2] - xy[:, 0]) * (xy[:, 3] - xy[:, 1])
        for i, j in zip(*np.triu_indices(len(g), k=1), strict=True):
            if iou[i, j] > dup_iou:
                dups.append((image, g.index[i], g.index[j], float(iou[i, j])))
                continue
            lt = np.maximum(xy[i, :2], xy[j, :2])
            rb = np.minimum(xy[i, 2:], xy[j, 2:])
            inter = float(np.clip(rb - lt, 0, None).prod())
            small = min(area[i], area[j])
            if small > 0 and inter / small >= nested_frac:
                nested.append((image, g.index[i], g.index[j], float(iou[i, j])))
    xy = _xyxy(geom)
    eps = 1e-6
    over = (xy[:, 0] < -eps) | (xy[:, 1] < -eps) | (xy[:, 2] > 1 + eps) | (xy[:, 3] > 1 + eps)
    cols = ["image", "boite_a", "boite_b", "iou"]
    return {
        "doublons": pd.DataFrame(dups, columns=cols),
        "imbriquees": pd.DataFrame(nested, columns=cols),
        "degenerees": geom[(geom["w_px"] < min_px) | (geom["h_px"] < min_px)],
        "debordantes": geom[over],
    }


def yolo_group_leaks(manifest: pd.DataFrame, index: pd.DataFrame | None = None) -> dict:
    """Groups in several splits. PlantVillage rows have no `groupe` in the manifest: with
    `index`, it is taken from there by `path`. The two group numberings are distinct
    (prefixed), so a YOLO group never matches an index group by accident."""
    m = manifest.copy()
    key = ("yolo:" + m["groupe"].dropna().astype(int).astype(str)).reindex(m.index)
    if index is not None:
        idx_group = index.set_index("path")["groupe"]
        from_index = m["path"].map(idx_group)
        fill = key.isna() & from_index.notna()
        key[fill] = "index:" + from_index[fill].astype(int).astype(str)
    m["cle_groupe"] = key
    leaks = group_leaks(m, "cle_groupe")
    return {
        "n_fuites": int(len(leaks)),
        "fuites": leaks,
        "non_controlees": int(m["cle_groupe"].isna().sum()),
        "non_controlees_par_source": m.loc[m["cle_groupe"].isna(), "source"]
        .value_counts()
        .to_dict(),
    }


# -------------------------------------------------------------- embeddings (§3.7, P2)


def extract_features(
    ckpt: Path, paths: Sequence[str], data_dir: Path, device: str = "cpu", batch: int = 64
) -> np.ndarray:
    """Backbone features (n, dim) of a classifier `best.pt` on the given index paths."""
    import torch

    from vision.datasets.augment import build_transform
    from vision.datasets.batch_augment import BatchAugment
    from vision.datasets.dataset import read_rgb
    from vision.train.train_classifier import load_checkpoint

    model, _, cfg = load_checkpoint(Path(ckpt), device)
    tf = build_transform("eval", cfg["data"]["size"])
    norm = BatchAugment("eval").to(device)
    feats = []
    with torch.inference_mode():
        for b in range(0, len(paths), batch):
            x = torch.stack([tf(image=read_rgb(Path(data_dir) / p))["image"]
                             for p in paths[b : b + batch]])  # fmt: skip
            feats.append(model.backbone(norm(x.to(device))).float().cpu().numpy())
    return np.concatenate(feats) if feats else np.empty((0, 0), np.float32)


def embed_2d(feats: np.ndarray, method: str = "umap", seed: int = 0) -> tuple[np.ndarray, str]:
    """(n, 2) projection and the method used: UMAP (extra `stats`) or t-SNE as a fallback."""
    if method == "umap":
        try:
            import umap

            return umap.UMAP(random_state=seed).fit_transform(feats), "umap"
        except ImportError:
            log.warning("umap-learn absent (extra `stats`) : t-SNE à la place")
    from sklearn.manifold import TSNE

    perplexity = min(30.0, max(2.0, (len(feats) - 1) / 3))
    return TSNE(2, perplexity=perplexity, random_state=seed, init="pca").fit_transform(
        feats
    ), "tsne"
