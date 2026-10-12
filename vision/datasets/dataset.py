"""Torch dataset over data/index.parquet for the multi-head classifier (docs/03-classifieur.md)."""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset, WeightedRandomSampler

from vision.datasets.taxonomy import Taxonomy

log = logging.getLogger(__name__)

IGNORE_INDEX = -100  # classe target of ambiguous classes: excluded from the classe loss
SANTE = ("sain", "anormal")
HEADS = ("espece", "sante", "classe")


@dataclass(frozen=True)
class LabelSpace:
    """Label vocabularies of the three heads, stored in every checkpoint."""

    especes: tuple[str, ...]
    sante: tuple[str, ...]
    classes: tuple[str, ...]  # non-ambiguous classes only
    taxonomy_version: int

    @classmethod
    def from_taxonomy(cls, taxo: Taxonomy) -> "LabelSpace":
        classes = sorted(c for c, info in taxo.classes.items() if not info.ambigu)
        return cls(tuple(sorted(taxo.especes)), SANTE, tuple(classes), taxo.version)

    def to_dict(self) -> dict:
        return {
            "especes": list(self.especes),
            "sante": list(self.sante),
            "classes": list(self.classes),
            "taxonomy_version": self.taxonomy_version,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "LabelSpace":
        return cls(
            tuple(d["especes"]), tuple(d["sante"]), tuple(d["classes"]), d["taxonomy_version"]
        )

    def sizes(self) -> dict[str, int]:
        return {"espece": len(self.especes), "sante": len(self.sante), "classe": len(self.classes)}

    def vocab(self, head: str) -> tuple[str, ...]:
        return {"espece": self.especes, "sante": self.sante, "classe": self.classes}[head]

    def encode(self, df: pd.DataFrame) -> np.ndarray:
        """(n, 3) int64 targets in HEADS order; ambiguous classes get IGNORE_INDEX."""
        out = np.empty((len(df), 3), dtype=np.int64)
        for j, head in enumerate(HEADS):
            idx = {name: i for i, name in enumerate(self.vocab(head))}
            col = df[head].astype(str)
            if head != "classe":
                missing = set(col) - set(idx)
                if missing:
                    raise KeyError(f"{head} inconnus du LabelSpace : {sorted(missing)}")
            out[:, j] = col.map(idx).fillna(IGNORE_INDEX).to_numpy(np.int64)
        return out


def drop_contradictory_groups(df: pd.DataFrame) -> pd.DataFrame:
    """Drop near-duplicate groups carrying several classes (label noise, docs/02 §3)."""
    n_classes = df.groupby("groupe", observed=True)["classe"].nunique()
    bad = df["groupe"].isin(n_classes.index[n_classes > 1])
    if bad.any():
        per_source = df.loc[bad, "source"].astype(str).value_counts().to_dict()
        log.info("groupes contradictoires : %d images écartées %s", bad.sum(), per_source)
    return df[~bad].reset_index(drop=True)


def load_index(
    index_path: Path, splits: Sequence[str] | None = None, sources: Sequence[str] | None = None
) -> pd.DataFrame:
    """Index rows of the given splits/sources, without contradictory groups.

    Contradictory groups are detected on the whole index, before filtering, so that a
    duplicate whose twin lies in another split is still dropped.
    """
    df = drop_contradictory_groups(pd.read_parquet(index_path))
    if splits is not None:
        df = df[df["split"].isin(splits)]
    if sources is not None:
        df = df[df["source"].isin(sources)]
    return df.reset_index(drop=True)


def stratified_subset(df: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    """About n rows, proportional to classe, at least one per classe (smoke tests)."""
    if n >= len(df):
        return df
    frac = n / len(df)
    parts = [
        g.sample(max(1, round(len(g) * frac)), random_state=seed)
        for _, g in df.groupby("classe", observed=True)
    ]
    return pd.concat(parts).reset_index(drop=True)


def read_rgb(path: Path) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise OSError(f"image illisible : {path}")
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


class PlantDataset(Dataset):
    """(uint8 image tensor, int64 targets [espece, sante, classe]) per index row.

    Images are normalized later, by batch on the device (batch_augment.BatchAugment).
    """

    def __init__(
        self,
        df: pd.DataFrame,
        labels: LabelSpace,
        transform: Callable[..., dict],
        data_dir: Path,
        bg_paster: Callable[[np.ndarray, np.ndarray], np.ndarray] | None = None,
    ):
        self.df = df.reset_index(drop=True)
        self.targets = labels.encode(self.df)
        self.paths = self.df["path"].tolist()
        self.masks = self.df["mask_path"].tolist() if "mask_path" in self.df else [None] * len(df)
        self.transform = transform
        self.data_dir = Path(data_dir)
        self.bg_paster = bg_paster

    def __len__(self) -> int:
        return len(self.paths)

    def __getitem__(self, i: int) -> tuple[torch.Tensor, torch.Tensor]:
        img = read_rgb(self.data_dir / self.paths[i])
        mask_path = self.masks[i]
        if self.bg_paster is not None and isinstance(mask_path, str):
            img = self.bg_paster(img, read_rgb(self.data_dir / mask_path))
        return self.transform(image=img)["image"], torch.from_numpy(self.targets[i])


def sampler_weights(classes: pd.Series) -> np.ndarray:
    """Per-sample weight proportional to 1/sqrt(count of its classe)."""
    counts = classes.map(classes.value_counts())
    return (1.0 / np.sqrt(counts.to_numpy(np.float64))).astype(np.float64)


def make_sampler(df: pd.DataFrame, seed: int) -> WeightedRandomSampler:
    gen = torch.Generator().manual_seed(seed)
    w = torch.as_tensor(sampler_weights(df["classe"].astype(str)))
    return WeightedRandomSampler(w, num_samples=len(df), replacement=True, generator=gen)
