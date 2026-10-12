"""Checks on data/index.parquet (docs/02-donnees.md §3). Skipped until the index is built."""

import warnings

import pandas as pd
import pytest

from vision.datasets.build_index import (
    DATA_DIR,
    INDEX_NAME,
    REJECTS_NAME,
    iter_source_dirs,
    list_images,
    low_eval_classes,
    read_index_meta,
)
from vision.datasets.taxonomy import load_taxonomy

INDEX = DATA_DIR / INDEX_NAME
pytestmark = pytest.mark.skipif(not INDEX.exists(), reason="index non construit")


def _rejects() -> set[str]:
    path = DATA_DIR / REJECTS_NAME
    if not path.exists():
        return set()
    return {ln.split("\t")[0] for ln in path.read_text(encoding="utf-8").splitlines()}


@pytest.fixture(scope="module")
def df():
    return pd.read_parquet(INDEX)


def test_no_group_across_splits(df):
    n_splits = df.groupby("groupe", observed=True)["split"].nunique()
    leaking = n_splits[n_splits > 1]
    assert leaking.empty, f"{len(leaking)} groupes à cheval sur plusieurs splits"


def test_counts_match_folders(df):
    rejects = _rejects()
    indexed = df.groupby(df["path"].str.rsplit("/", n=1).str[0]).size()
    for sd in iter_source_dirs(DATA_DIR):
        rel = str(sd.path.relative_to(DATA_DIR))
        expected = sum(str(p.relative_to(DATA_DIR)) not in rejects for p in list_images(sd.path))
        assert indexed.get(rel, 0) == expected, rel


def test_known_count(df):
    folder = DATA_DIR / "ccmt/raw/Tomato/healthy"
    if not folder.exists():
        pytest.skip("CCMT absent")
    assert len(list_images(folder)) == 470
    indexed = df["path"].str.startswith("ccmt/raw/Tomato/healthy/").sum()
    assert (
        indexed
        + len(_rejects() & {f"ccmt/raw/Tomato/healthy/{p.name}" for p in list_images(folder)})
        == 470
    )


def test_plantdoc_only_xdomain(df):
    assert (df.loc[df["source"] == "plantdoc", "split"] == "test_xdomain").all()
    assert (df.loc[df["split"] == "test_xdomain", "source"] == "plantdoc").all()


def test_split_proportions(df):
    labo = df[df["source"].isin(["plantvillage", "ccmt"])]
    frac = labo["split"].value_counts(normalize=True)
    assert frac["train"] == pytest.approx(0.8, abs=0.03)
    assert frac["val"] == pytest.approx(0.1, abs=0.02)
    assert frac["test"] == pytest.approx(0.1, abs=0.02)


def test_taxonomy_version(df):
    assert read_index_meta(INDEX)["taxonomy_version"] == load_taxonomy().version


def test_min_eval_per_class(df):
    low = low_eval_classes(df, min_eval=20)
    for c, msg in low.items():
        warnings.warn(f"{c} : {msg}", stacklevel=1)
