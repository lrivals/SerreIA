"""Build data/index.parquet: one row per image (docs/02-donnees.md §3).

python -m vision.datasets.build_index [--data-dir data] [--workers 16] [--no-cache]
"""

import argparse
import json
import logging
import os
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import imagehash
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from PIL import Image
from sklearn.model_selection import StratifiedGroupKFold
from tqdm import tqdm

from vision.datasets.near_duplicates import group_near_duplicates
from vision.datasets.taxonomy import Taxonomy, UnmappedError, load_taxonomy

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
INDEX_NAME = "index.parquet"
CACHE_NAME = ".cache/hashes.parquet"
REJECTS_NAME = "index_rejets.txt"
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
MAX_HAMMING = 6  # pHash
MAX_HAMMING_CONFIRM = 8  # dHash, filters pHash false positives (see near_duplicates)
N_FOLDS = 10  # fold 0 -> test, fold 1 -> val, rest -> train: 80 / 10 / 10
SEED = 42
HASH_DTYPES = {"width": "int32", "height": "int32", "phash": "uint64", "dhash": "uint64"}
HASH_COLS = list(HASH_DTYPES)
LARGE_GROUP = 200  # above this, near-duplicate chaining is suspicious


@dataclass(frozen=True)
class SourceDir:
    source: str
    key: str  # taxonomy key (folder name or VOC label)
    path: Path


def iter_source_dirs(data_dir: Path) -> Iterator[SourceDir]:
    """Every class folder of every source present on disk."""
    pv = data_dir / "plantvillage" / "color"
    if pv.exists():
        for d in sorted(pv.iterdir()):
            yield SourceDir("plantvillage", d.name, d)
    ccmt = data_dir / "ccmt" / "raw"
    if ccmt.exists():
        for crop in sorted(ccmt.iterdir()):
            for d in sorted(crop.iterdir()):
                yield SourceDir("ccmt", f"{crop.name}/{d.name}", d)
    crops = data_dir / "plantdoc" / "crops"
    if crops.exists():
        for split in sorted(crops.iterdir()):
            for d in sorted(split.iterdir()):
                yield SourceDir("plantdoc", d.name, d)


def list_images(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS)


def mask_for(data_dir: Path, img: Path) -> str | None:
    """PlantVillage segmented/ mask path (relative to data_dir) if it exists."""
    mask = (
        data_dir / "plantvillage" / "segmented" / img.parent.name / f"{img.stem}_final_masked.jpg"
    )
    return str(mask.relative_to(data_dir)) if mask.exists() else None


def collect(data_dir: Path, taxo: Taxonomy) -> pd.DataFrame:
    rows, unmapped = [], []
    for sd in iter_source_dirs(data_dir):
        try:
            info = taxo.lookup(sd.source, sd.key)
        except UnmappedError:
            unmapped.append(f"{sd.source}: {sd.key!r}")
            continue
        for img in list_images(sd.path):
            rows.append(
                {
                    "path": str(img.relative_to(data_dir)),
                    "source": sd.source,
                    "espece": info.espece,
                    "etat": info.etat,
                    "classe": info.classe,
                    "sante": info.sante,
                    "ambigu": info.ambigu,
                    "mask_path": mask_for(data_dir, img) if sd.source == "plantvillage" else None,
                }
            )
    if unmapped:
        raise UnmappedError("dossiers non mappés dans taxonomy.yaml :\n  " + "\n  ".join(unmapped))
    if not rows:
        raise SystemExit(f"aucune image trouvée sous {data_dir}")
    return pd.DataFrame(rows)


def _hash_one(path: str) -> tuple[int, int, int, int] | str:
    """(width, height, phash, dhash) or an error message for a corrupt file."""
    try:
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            im.load()
            w, h = im.size
            return w, h, int(str(imagehash.phash(im)), 16), int(str(imagehash.dhash(im)), 16)
    except Exception as e:  # noqa: BLE001 - any decoding failure means a rejected file
        return f"{type(e).__name__}: {e}"


def compute_hashes(
    data_dir: Path, paths: list[str], workers: int, use_cache: bool
) -> tuple[pd.DataFrame, dict[str, str]]:
    """width / height / phash / dhash per path, with a (path, size, mtime) cache."""
    stats = [os.stat(data_dir / p) for p in paths]
    todo = pd.DataFrame(
        {"path": paths, "size": [s.st_size for s in stats], "mtime": [s.st_mtime_ns for s in stats]}
    )
    cache_path = data_dir / CACHE_NAME
    cached = pd.read_parquet(cache_path) if use_cache and cache_path.exists() else None
    # Inner merge only: a left merge would turn the uint64 phash into float64 and lose bits.
    hits = todo.merge(cached, on=["path", "size", "mtime"]) if cached is not None else None
    hit_paths = set(hits["path"]) if hits is not None else set()
    to_hash = [p for p in paths if p not in hit_paths]
    log.info("pHash : %d en cache, %d à calculer", len(hit_paths), len(to_hash))

    rejects: dict[str, str] = {}
    new_rows = []
    if to_hash:
        abs_paths = [str(data_dir / p) for p in to_hash]
        with ProcessPoolExecutor(workers) as pool:
            results = pool.map(_hash_one, abs_paths, chunksize=64)
            for p, res in zip(
                to_hash, tqdm(results, total=len(to_hash), desc="pHash"), strict=True
            ):
                if isinstance(res, str):
                    rejects[p] = res
                else:
                    new_rows.append((p, *res))
    new = pd.DataFrame(new_rows, columns=["path", *HASH_COLS])
    new = new.astype(HASH_DTYPES).merge(todo, on="path")
    done = pd.concat([d for d in (hits, new) if d is not None and len(d)], ignore_index=True)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    parts = [done]
    if cached is not None:
        parts.insert(0, cached[~cached["path"].isin(done["path"])])
    pd.concat(parts, ignore_index=True).to_parquet(cache_path)
    return done[["path", *HASH_COLS]], rejects


def assign_splits(df: pd.DataFrame) -> pd.Series:
    split = pd.Series("test_xdomain", index=df.index, dtype=object)
    labo = df.index[df["source"].isin(["plantvillage", "ccmt"])]
    sgkf = StratifiedGroupKFold(n_splits=N_FOLDS, shuffle=True, random_state=SEED)
    folds = sgkf.split(labo, df.loc[labo, "classe"], df.loc[labo, "groupe"])
    split.loc[labo] = "train"
    for k, (_, test_idx) in enumerate(folds):
        if k == 0:
            split.loc[labo[test_idx]] = "test"
        elif k == 1:
            split.loc[labo[test_idx]] = "val"
        else:
            break
    return split


def build_index(data_dir: Path, workers: int, use_cache: bool) -> tuple[pd.DataFrame, dict]:
    taxo = load_taxonomy()
    df = collect(data_dir, taxo)
    hashes, rejects = compute_hashes(data_dir, df["path"].tolist(), workers, use_cache)
    df = df.merge(hashes, on="path", how="inner")
    df["groupe"] = group_near_duplicates(
        df["phash"].to_numpy(), MAX_HAMMING, df["dhash"].to_numpy(), MAX_HAMMING_CONFIRM
    )
    # A PlantDoc crop grouped with a training-source image would contaminate test_xdomain.
    labo_groups = set(df.loc[df["source"] != "plantdoc", "groupe"])
    leaks = (df["source"] == "plantdoc") & df["groupe"].isin(labo_groups)
    for p in df.loc[leaks, "path"]:
        rejects[p] = "quasi-doublon d'une image PlantVillage/CCMT (exclu de test_xdomain)"
    df = df[~leaks].reset_index(drop=True)
    df["split"] = assign_splits(df)

    cols = ["path", "source", "espece", "etat", "classe", "sante", "ambigu"]
    cols += [*HASH_COLS, "groupe", "split", "mask_path"]
    df = df[cols].sort_values("path", ignore_index=True)
    for c in ["source", "espece", "etat", "classe", "sante", "split"]:
        df[c] = df[c].astype("category")
    meta = {
        "taxonomy_version": taxo.version,
        "max_hamming": MAX_HAMMING,
        "max_hamming_confirm": MAX_HAMMING_CONFIRM,
        "seed": SEED,
    }
    return df, {"meta": meta, "rejects": rejects}


def write_index(df: pd.DataFrame, meta: dict, path: Path) -> None:
    table = pa.Table.from_pandas(df, preserve_index=False)
    schema_meta = {**(table.schema.metadata or {}), b"serreia": json.dumps(meta).encode()}
    pq.write_table(table.replace_schema_metadata(schema_meta), path)


def read_index_meta(path: Path) -> dict:
    return json.loads(pq.read_schema(path).metadata[b"serreia"])


def low_eval_classes(df: pd.DataFrame, min_eval: int) -> dict[str, str]:
    """Training classes with fewer than min_eval images in val or test."""
    labo = df[df["split"].isin(["train", "val", "test"])]
    counts = pd.crosstab(labo["classe"].astype(str), labo["split"].astype(str))
    out = {}
    for c, row in counts.iterrows():
        low = [f"{row.get(s, 0)} en {s}" for s in ("val", "test") if row.get(s, 0) < min_eval]
        if low:
            out[c] = ", ".join(low) + f" (< {min_eval})"
    return out


def report(df: pd.DataFrame, rejects: dict[str, str], min_eval: int) -> None:
    print("\n=== Index ===")
    print(f"{len(df)} images, {df['espece'].nunique()} espèces, {df['classe'].nunique()} classes")
    print("\nSource × split :")
    print(pd.crosstab(df["source"], df["split"], margins=True).to_string())

    sizes = df["groupe"].value_counts()
    print(
        f"\nGroupes : {len(sizes)} ({(sizes > 1).sum()} de quasi-doublons, "
        f"{sizes[sizes > 1].sum()} images concernées, max {sizes.max()})"
    )
    if sizes.max() > LARGE_GROUP:
        log.warning("groupe de %d images : chaînage suspect, vérifier MAX_HAMMING", sizes.max())

    per_class = pd.crosstab(df["classe"], df["split"])
    print("\nEffectifs par classe :")
    print(per_class.to_string())
    for c, n in low_eval_classes(df, min_eval).items():
        log.warning("classe %s : %s", c, n)

    print(f"\nFichiers rejetés : {len(rejects)}")
    for p, err in sorted(rejects.items()):
        print(f"  {p} : {err}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--workers", type=int, default=os.cpu_count())
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--min-eval", type=int, default=20, help="seuil d'alerte val/test")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    df, extra = build_index(args.data_dir, args.workers, not args.no_cache)
    out = args.data_dir / INDEX_NAME
    write_index(df, extra["meta"], out)
    rejects = extra["rejects"]
    (args.data_dir / REJECTS_NAME).write_text(
        "".join(f"{p}\t{e}\n" for p, e in sorted(rejects.items())), encoding="utf-8"
    )
    report(df, rejects, args.min_eval)
    print(f"\nÉcrit : {out}")


if __name__ == "__main__":
    main()
