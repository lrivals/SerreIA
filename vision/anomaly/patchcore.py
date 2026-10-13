"""PatchCore anomaly detection, trained on healthy greenhouse images only (docs/04 §4).

    python -m vision.anomaly.patchcore fit --images data/serre/sain/tomate --espece tomate
    python -m vision.anomaly.patchcore score --espece tomate --images data/serre/a_verifier

For problems no dataset covers (N/K/Mg deficiencies, light burn, water stress, etiolation).
Per species: pretrained CNN features of the healthy images (no training), a coreset of their
patches as memory bank; the anomaly score of a patch is its distance to the nearest bank
patch, the image score the maximum. Threshold: quantile (99th) of held-out healthy scores.
In-house implementation (Roth et al. 2022) to avoid the anomalib dependency.
"""

import argparse
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import timm
import torch
import torch.nn.functional as F
from torch import nn

from vision.datasets.batch_augment import MEAN, STD
from vision.datasets.build_index import IMAGE_EXTS
from vision.datasets.dataset import read_rgb
from vision.train.train_classifier import RUNS_DIR, pick_device

log = logging.getLogger(__name__)

MODELS_DIR = RUNS_DIR / "patchcore"


@dataclass
class PatchCoreConfig:
    backbone: str = "wide_resnet50_2"
    layers: tuple[int, ...] = (2, 3)  # mid-level features: local texture and colour
    size: int = 224
    coreset_ratio: float = 0.1
    proj_dim: int = 128  # random projection used only to pick the coreset
    quantile: float = 0.99
    pretrained: bool = True


class FeatureExtractor(nn.Module):
    """Concatenated, locally averaged (3×3) features of the chosen layers, at the resolution
    of the first one: (n, C, h, w)."""

    def __init__(self, cfg: PatchCoreConfig):
        super().__init__()
        self.net = timm.create_model(
            cfg.backbone, pretrained=cfg.pretrained, features_only=True, out_indices=cfg.layers
        ).eval()
        self.register_buffer("mean", torch.tensor(MEAN).view(1, 3, 1, 1), persistent=False)
        self.register_buffer("std", torch.tensor(STD).view(1, 3, 1, 1), persistent=False)

    @torch.no_grad()
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        feats = self.net((x - self.mean) / self.std)
        size = feats[0].shape[-2:]
        feats = [F.avg_pool2d(f, 3, stride=1, padding=1) for f in feats]
        feats = [F.interpolate(f, size, mode="bilinear", align_corners=False) for f in feats]
        return torch.cat(feats, 1)


def greedy_coreset(x: torch.Tensor, n: int, proj_dim: int = 128, seed: int = 0) -> torch.Tensor:
    """Indices of n points covering x (k-center greedy on a random projection)."""
    if n >= len(x):
        return torch.arange(len(x), device=x.device)
    g = torch.Generator(device="cpu").manual_seed(seed)
    if x.shape[1] > proj_dim:
        proj = torch.randn(x.shape[1], proj_dim, generator=g).to(x.device) / proj_dim**0.5
        x = x @ proj
    idx = [int(torch.randint(len(x), (1,), generator=g))]
    dist = torch.cdist(x, x[idx]).squeeze(1)
    for _ in range(n - 1):
        i = int(dist.argmax())
        idx.append(i)
        dist = torch.minimum(dist, torch.cdist(x, x[i : i + 1]).squeeze(1))
    return torch.tensor(idx, device=x.device)


def nearest_dist(q: torch.Tensor, bank: torch.Tensor, chunk: int = 4096) -> torch.Tensor:
    return torch.cat([torch.cdist(q[i : i + chunk], bank).min(1).values
                      for i in range(0, len(q), chunk)])  # fmt: skip


def to_tensor(imgs: Sequence[np.ndarray], size: int) -> torch.Tensor:
    """RGB uint8 images -> (n, 3, size, size) float in [0, 1]."""
    x = torch.stack([torch.from_numpy(np.ascontiguousarray(i)).permute(2, 0, 1) for i in imgs])
    return F.interpolate(x.float() / 255, (size, size), mode="bilinear", antialias=True)


class PatchCore:
    def __init__(self, cfg: PatchCoreConfig | None = None, device: torch.device | str = "cpu"):
        self.cfg = cfg or PatchCoreConfig()
        self.device = torch.device(device)
        self.extractor = FeatureExtractor(self.cfg).to(self.device)
        self.bank: torch.Tensor | None = None
        self.threshold: float | None = None

    def _patches(self, imgs, batch: int = 16) -> tuple[torch.Tensor, tuple[int, int]]:
        out = []
        for i in range(0, len(imgs), batch):
            x = to_tensor(imgs[i : i + batch], self.cfg.size).to(self.device)
            out.append(self.extractor(x))
        f = torch.cat(out)
        return f.permute(0, 2, 3, 1).reshape(len(f), -1, f.shape[1]), tuple(f.shape[-2:])

    def fit(self, imgs: Sequence[np.ndarray]) -> "PatchCore":
        patches, _ = self._patches(imgs)
        flat = patches.reshape(-1, patches.shape[-1])
        n = max(1, round(self.cfg.coreset_ratio * len(flat)))
        self.bank = flat[greedy_coreset(flat, n, self.cfg.proj_dim)].contiguous()
        log.info("PatchCore : %d patchs -> banque de %d", len(flat), len(self.bank))
        return self

    def score(self, imgs: Sequence[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
        """(image scores (n,), anomaly maps (n, size, size)); resize a map to its image
        for display."""
        if self.bank is None:
            raise RuntimeError("PatchCore non entraîné : fit() ou load()")
        patches, (h, w) = self._patches(imgs)
        d = torch.stack([nearest_dist(p, self.bank) for p in patches]).reshape(-1, 1, h, w)
        maps = F.interpolate(d, self.cfg.size, mode="bilinear", align_corners=False)
        maps = _gaussian_blur(maps, sigma=4)
        return d.amax((1, 2, 3)).cpu().numpy(), maps[:, 0].cpu().numpy()

    def calibrate(self, healthy_val: Sequence[np.ndarray]) -> float:
        scores, _ = self.score(healthy_val)
        self.threshold = float(np.quantile(scores, self.cfg.quantile))
        return self.threshold

    def is_anomalous(self, scores: np.ndarray) -> np.ndarray:
        if self.threshold is None:
            raise RuntimeError("seuil non calibré : calibrate()")
        return scores > self.threshold

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {"config": vars(self.cfg), "bank": self.bank.cpu(), "threshold": self.threshold}, path
        )

    @classmethod
    def load(cls, path: Path, device: torch.device | str = "cpu") -> "PatchCore":
        ckpt = torch.load(path, map_location="cpu", weights_only=False)
        cfg = PatchCoreConfig(**{**ckpt["config"], "layers": tuple(ckpt["config"]["layers"])})
        model = cls(cfg, device)
        model.bank, model.threshold = ckpt["bank"].to(model.device), ckpt["threshold"]
        return model


def _gaussian_blur(x: torch.Tensor, sigma: float) -> torch.Tensor:
    r = int(3 * sigma)
    k = torch.exp(-(torch.arange(-r, r + 1, device=x.device, dtype=x.dtype) ** 2) / (2 * sigma**2))
    k = k / k.sum()
    x = F.conv2d(F.pad(x, (r, r, 0, 0), mode="reflect"), k.view(1, 1, 1, -1))
    return F.conv2d(F.pad(x, (0, 0, r, r), mode="reflect"), k.view(1, 1, -1, 1))


def list_images(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.suffix.lower() in IMAGE_EXTS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_fit = sub.add_parser("fit", help="banque de patchs + seuil, images saines")
    p_fit.add_argument("--val-frac", type=float, default=0.2, help="part réservée au seuil")
    p_fit.add_argument("--backbone", default=PatchCoreConfig.backbone)
    p_score = sub.add_parser("score", help="score d'anomalie d'images")
    for p in (p_fit, p_score):
        p.add_argument("--images", type=Path, required=True)
        p.add_argument("--espece", required=True)
        p.add_argument("--device", default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    device = pick_device(args.device)
    path = MODELS_DIR / f"{args.espece}.pt"
    paths = list_images(args.images)
    if not paths:
        raise SystemExit(f"aucune image sous {args.images}")

    if args.cmd == "fit":
        rng = np.random.default_rng(0)
        order = rng.permutation(len(paths))
        n_val = max(1, round(args.val_frac * len(paths)))
        val, train = [paths[i] for i in order[:n_val]], [paths[i] for i in order[n_val:]]
        model = PatchCore(PatchCoreConfig(backbone=args.backbone), device)
        model.fit([read_rgb(p) for p in train])
        thr = model.calibrate([read_rgb(p) for p in val])
        model.save(path)
        log.info("%s : %d images, seuil %.4f -> %s", args.espece, len(train), thr, path)
    else:
        model = PatchCore.load(path, device)
        scores, _ = model.score([read_rgb(p) for p in paths])
        flags = model.is_anomalous(scores)
        for p, s, a in zip(paths, scores, flags, strict=True):
            print(f"{'ANOMALIE' if a else 'ok':8s} {s:8.4f}  {p}")


if __name__ == "__main__":
    main()
