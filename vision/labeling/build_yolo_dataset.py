"""YOLO detection dataset `data/yolo/` from PlantDoc and PlantVillage (docs/04 §2, §3).

python -m vision.labeling.build_yolo_dataset [--pv-per-class 40] [--preview]

- PlantDoc: VOC boxes, every label -> `feuille`. PlantDoc TEST -> `test`; TRAIN -> train / val
  grouped by pHash + dHash (same thresholds as the index); a TRAIN image near-duplicate of a
  TEST image is dropped.
- PlantVillage `segmented/`: one leaf per image, box from the mask; a sample per classe, in
  the split of `index.parquet` (no leak with the classifier).

Images are relative symlinks to data/ (`get_datasets.sh pack` follows them). Images with an
EXIF rotation are re-encoded without it, so every reader sees the pixels the boxes refer to;
truncated JPEGs too (Ultralytics would otherwise rewrite them in place of the link).
The output is rebuilt from scratch (images/ and labels/ only).
"""

import argparse
import logging
import os
import shutil
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
from PIL import Image
from sklearn.model_selection import GroupShuffleSplit

from vision.datasets.augment import leaf_mask
from vision.datasets.build_index import (
    DATA_DIR,
    INDEX_NAME,
    MAX_HAMMING,
    MAX_HAMMING_CONFIRM,
    SEED,
    _hash_one,
)
from vision.datasets.dataset import read_rgb
from vision.datasets.near_duplicates import group_near_duplicates
from vision.datasets.prepare import _safe_name, voc_boxes
from vision.labeling.yolo_format import (
    CLASSES,
    SPLITS,
    from_yolo,
    label_path,
    mask_to_box,
    read_labels,
    to_yolo,
    write_data_yaml,
    write_labels,
)

log = logging.getLogger(__name__)

OUT_NAME = "yolo"
MANIFEST = "manifest.parquet"
FEUILLE = CLASSES.index("feuille")
MIN_BOX = 4  # px, smaller boxes are annotation noise
VAL_FRAC = 0.1
EXIF_ORIENTATION = 274


def plantdoc_rows(data_dir: Path) -> pd.DataFrame:
    """One row per PlantDoc image: path (relative to data/), source split, size, boxes."""
    rows = []
    for split in ("train", "test"):
        for xml_path in sorted((data_dir / "plantdoc" / split).glob("*.xml")):
            try:
                found = voc_boxes(xml_path)
            except (ET.ParseError, OSError, TypeError, ValueError) as e:
                log.warning("ignoré %s : %s", xml_path.name, e)
                continue
            if found is None:
                log.warning("image manquante : %s", xml_path.name)
                continue
            img_path, (w, h), boxes = found
            yolo = [
                to_yolo(FEUILLE, b, w, h)
                for _, b in boxes
                if b[2] - b[0] >= MIN_BOX and b[3] - b[1] >= MIN_BOX
            ]
            rel = str(img_path.relative_to(data_dir))
            rows.append({"path": rel, "orig": split, "width": w, "height": h, "boxes": yolo})
    return pd.DataFrame(rows)


def plantdoc_splits(df: pd.DataFrame, hashes: np.ndarray, seed: int = SEED) -> pd.DataFrame:
    """split (train / val / test) and groupe per PlantDoc row; drops TRAIN images
    near-duplicate of a TEST image. hashes: (n, 2) pHash, dHash."""
    df = df.copy()
    df["groupe"] = group_near_duplicates(
        hashes[:, 0], MAX_HAMMING, hashes[:, 1], MAX_HAMMING_CONFIRM
    )
    test_groups = set(df.loc[df["orig"] == "test", "groupe"])
    leak = (df["orig"] == "train") & df["groupe"].isin(test_groups)
    if leak.any():
        log.info("PlantDoc : %d images TRAIN quasi-doublons de TEST, écartées", leak.sum())
    df = df[~leak].reset_index(drop=True)
    df["split"] = "test"
    train = df.index[df["orig"] == "train"]
    gss = GroupShuffleSplit(n_splits=1, test_size=VAL_FRAC, random_state=seed)
    tr, va = next(gss.split(train, groups=df.loc[train, "groupe"]))
    df.loc[train[tr], "split"] = "train"
    df.loc[train[va], "split"] = "val"
    return df


def hash_images(data_dir: Path, paths: list[str], workers: int) -> np.ndarray:
    with ProcessPoolExecutor(workers) as pool:
        res = list(pool.map(_hash_one, [str(data_dir / p) for p in paths], chunksize=32))
    bad = [p for p, r in zip(paths, res, strict=True) if isinstance(r, str)]
    if bad:
        raise OSError(f"images illisibles : {bad[:5]}")
    return np.array([(r[2], r[3]) for r in res], dtype=np.uint64)


def plantvillage_rows(data_dir: Path, per_class: int, seed: int = SEED) -> pd.DataFrame:
    """per_class train images per classe (per_class // 8 in val and test), box from the mask."""
    if per_class <= 0:
        return pd.DataFrame(columns=["path", "split", "width", "height", "boxes"])
    idx = pd.read_parquet(data_dir / INDEX_NAME)
    idx = idx[(idx["source"] == "plantvillage") & idx["mask_path"].notna()]
    quota = {"train": per_class, "val": max(1, per_class // 8), "test": max(1, per_class // 8)}
    parts = []
    for (_, split), g in idx.groupby(["classe", "split"], observed=True):
        if split in quota and len(g):
            parts.append(g.sample(min(quota[split], len(g)), random_state=seed))
    rows = []
    for r in pd.concat(parts).itertuples():
        mask = leaf_mask(read_rgb(data_dir / r.mask_path))
        box = mask_to_box(mask)
        if box is None:
            continue
        h, w = mask.shape
        rows.append(
            {"path": r.path, "split": str(r.split), "width": w, "height": h,
             "boxes": [to_yolo(FEUILLE, box, w, h)]}
        )  # fmt: skip
    return pd.DataFrame(rows)


def needs_copy(path: Path) -> bool:
    """EXIF rotation tag, or a JPEG without its end marker."""
    with Image.open(path) as im:
        if im.getexif().get(EXIF_ORIENTATION, 1) not in (0, 1):
            return True
        if im.format != "JPEG":
            return False
    with open(path, "rb") as f:
        f.seek(-2, os.SEEK_END)
        return f.read() != b"\xff\xd9"


def link_image(src: Path, dst: Path) -> Path:
    """Relative symlink, or a clean JPEG copy (see needs_copy)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if needs_copy(src):
        dst = dst.with_suffix(".jpg")
        with Image.open(src) as im:  # raw pixels, as voc_boxes measured them
            im.convert("RGB").save(dst, quality=95)
    else:
        dst.symlink_to(os.path.relpath(src, dst.parent))
    return dst


def write_dataset(data_dir: Path, out: Path, df: pd.DataFrame) -> pd.DataFrame:
    """Writes images/ labels/ data.yaml manifest; df: source, path, split, boxes."""
    for sub in ("images", "labels"):
        shutil.rmtree(out / sub, ignore_errors=True)
    images, seen = [], set()
    for r in df.itertuples():
        src = data_dir / r.path
        name = f"{r.source}_{_safe_name(Path(r.path).stem)}"
        while (r.split, name) in seen:  # same stem in two source folders
            name += "_"
        seen.add((r.split, name))
        dst = link_image(src, out / "images" / r.split / (name + src.suffix.lower()))
        write_labels(label_path(dst), r.boxes)
        images.append(str(dst.relative_to(out)))
    write_data_yaml(out)
    manifest = df.assign(image=images, n_boxes=df["boxes"].map(len)).drop(columns="boxes")
    manifest.to_parquet(out / MANIFEST, index=False)
    return manifest


def build(data_dir: Path, out: Path, pv_per_class: int, workers: int) -> pd.DataFrame:
    pd_rows = plantdoc_rows(data_dir)
    hashes = hash_images(data_dir, pd_rows["path"].tolist(), workers)
    pd_rows = plantdoc_splits(pd_rows, hashes).assign(source="plantdoc")
    pv_rows = plantvillage_rows(data_dir, pv_per_class).assign(source="plantvillage", orig="")
    df = pd.concat([pd_rows, pv_rows], ignore_index=True)
    return write_dataset(data_dir, out, df)


def report(manifest: pd.DataFrame) -> None:
    print("\nImages par split et source :")
    print(pd.crosstab(manifest["source"], manifest["split"], margins=True).to_string())
    print("\nBoîtes par split et source :")
    boxes = manifest.pivot_table("n_boxes", "source", "split", aggfunc="sum", margins=True)
    print(boxes.to_string())
    print(f"\nimages sans boîte : {(manifest['n_boxes'] == 0).sum()}")


def draw_boxes(img: np.ndarray, boxes, color=(255, 0, 0), labels=None) -> np.ndarray:
    """RGB copy with pixel boxes (x0, y0, x1, y1) drawn, optional text per box."""
    out = img.copy()
    t = max(1, round(max(img.shape[:2]) / 300))
    for i, (x0, y0, x1, y1) in enumerate(boxes):
        cv2.rectangle(out, (int(x0), int(y0)), (int(x1), int(y1)), color, t)
        if labels is not None:
            cv2.putText(out, labels[i], (int(x0), max(0, int(y0) - 3)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4 * t, color, t)  # fmt: skip
    return out


def preview(out: Path, split: str = "train", n: int = 16, seed: int = 0, path: Path | None = None):
    """Sheet of n images of a split with their boxes; saved to path if given."""
    from matplotlib.figure import Figure

    manifest = pd.read_parquet(out / MANIFEST)
    sub = manifest[manifest["split"] == split].sample(n, random_state=seed)
    cols = 4
    fig = Figure(figsize=(cols * 3, -(-len(sub) // cols) * 3))
    axes = np.atleast_1d(fig.subplots(-(-len(sub) // cols), cols)).ravel()
    for ax in axes:
        ax.axis("off")
    for ax, r in zip(axes, sub.itertuples(), strict=False):
        img = read_rgb(out / r.image)
        h, w = img.shape[:2]
        boxes = [from_yolo(b, w, h)[1] for b in read_labels(label_path(out / r.image))]
        ax.imshow(draw_boxes(img, boxes))
        ax.set_title(f"{r.source} ({len(boxes)})", fontsize=7)
    fig.tight_layout()
    if path is not None:
        fig.savefig(path, dpi=120)
    return fig


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--out", type=Path, default=None, help="défaut : <data-dir>/yolo")
    parser.add_argument("--pv-per-class", type=int, default=40, help="0 : PlantDoc seul")
    parser.add_argument("--workers", type=int, default=os.cpu_count())
    parser.add_argument("--preview", action="store_true", help="planche <out>/preview_<split>.png")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    out = args.out or args.data_dir / OUT_NAME
    manifest = build(args.data_dir, out, args.pv_per_class, args.workers)
    report(manifest)
    if args.preview:
        for split in SPLITS:
            preview(out, split, path=out / f"preview_{split}.png")
    print(f"\n{out / 'data.yaml'} écrit")


if __name__ == "__main__":
    main()
