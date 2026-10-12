"""Grad-CAM sheets per source and head, as a shortcut detector (docs/03 §3.3, §5).

python -m vision.eval.gradcam --run <mlflow_run_id> [--n 32] [--save-cams]
Writes reports/<run>/gradcam_<split>_<source>_<head>.png (half correct, half wrong
predictions) and, with --save-cams, the raw maps (.npz) reused as YOLO pre-annotations.
"""

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from matplotlib.figure import Figure
from pytorch_grad_cam import GradCAM
from pytorch_grad_cam.utils.image import show_cam_on_image
from pytorch_grad_cam.utils.model_targets import ClassifierOutputTarget
from torch import nn

from vision.datasets.dataset import HEADS, IGNORE_INDEX, LabelSpace, load_index
from vision.eval.metrics import collect_predictions
from vision.models.multihead import MultiHeadClassifier
from vision.train.config import resolve
from vision.train.train_classifier import RUNS_DIR, load_checkpoint, make_loader, pick_device

log = logging.getLogger(__name__)

REPORTS_DIR = RUNS_DIR.parent / "reports"
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
POOL = 512  # images predicted per source to pick correct / wrong examples from


class HeadOutput(nn.Module):
    """Exposes one head of the multi-head model as a plain classifier."""

    def __init__(self, model: MultiHeadClassifier, head: str):
        super().__init__()
        self.model, self.idx = model, HEADS.index(head)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.model(x)[self.idx]


def compute_cams(
    model: MultiHeadClassifier, head: str, x: torch.Tensor, classes: list[int], batch: int = 16
) -> np.ndarray:
    """(n, H, W) Grad-CAM maps in [0, 1] for the given class of each image."""
    out = []
    with GradCAM(
        model=HeadOutput(model, head), target_layers=[model.last_conv(x.shape[-1])]
    ) as cam:
        for i in range(0, len(x), batch):
            targets = [ClassifierOutputTarget(c) for c in classes[i : i + batch]]
            out.append(cam(input_tensor=x[i : i + batch], targets=targets))
    return np.concatenate(out) if out else np.zeros((0, *x.shape[-2:]), np.float32)


def denormalize(x: torch.Tensor) -> np.ndarray:
    img = x.permute(0, 2, 3, 1).cpu().numpy() * STD + MEAN
    return np.clip(img, 0, 1)


def pick_examples(pred: np.ndarray, target: np.ndarray, n: int, seed: int) -> np.ndarray:
    """Up to n/2 correct and n/2 wrong indices (topped up from the other side if short)."""
    rng = np.random.default_rng(seed)
    valid = target != IGNORE_INDEX
    good = rng.permutation(np.flatnonzero(valid & (pred == target)))
    bad = rng.permutation(np.flatnonzero(valid & (pred != target)))
    n_bad = min(len(bad), n // 2)
    n_good = min(len(good), n - n_bad)
    n_bad = min(len(bad), n - n_good)
    return np.concatenate([good[:n_good], bad[:n_bad]])


def plot_sheet(
    imgs: np.ndarray, cams: np.ndarray, titles: list[str], ok: np.ndarray, title: str, path: Path
) -> None:
    cols = 8
    rows = max(1, -(-len(imgs) // cols))
    fig = Figure(figsize=(cols * 2, rows * 2.3))
    axes = np.atleast_1d(fig.subplots(rows, cols)).ravel()
    for ax in axes:
        ax.axis("off")
    for ax, img, cam, t, good in zip(axes, imgs, cams, titles, ok, strict=False):
        ax.imshow(show_cam_on_image(img, cam, use_rgb=True))
        ax.set_title(t, fontsize=5, color="green" if good else "red")
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(path, dpi=150)


def short(name: str) -> str:
    return name.split("/", 1)[1] if "/" in name else name


def sheet_for(
    model: MultiHeadClassifier,
    labels: LabelSpace,
    cfg: dict,
    df: pd.DataFrame,
    n: int,
    out_dir: Path,
    tag: str,
    save_cams: bool,
    device: torch.device,
) -> list[Path]:
    pool = df.sample(min(POOL, len(df)), random_state=cfg["seed"]).reset_index(drop=True)
    loader = make_loader(pool, labels, cfg, train=False)
    preds = collect_predictions(model, loader, device)
    written = []
    for head in HEADS:
        vocab = labels.vocab(head)
        pred = preds.logits[head].argmax(1)
        target = preds.target(head)
        idx = pick_examples(pred, target, n, cfg["seed"])
        if len(idx) == 0:
            continue
        x = torch.stack([loader.dataset[int(i)][0] for i in idx]).to(device)
        cams = compute_cams(model, head, x, pred[idx].tolist())
        ok = pred[idx] == target[idx]
        titles = [
            f"{short(vocab[t])}\n→ {short(vocab[p])}"
            for t, p in zip(target[idx], pred[idx], strict=True)
        ]
        sheet = out_dir / f"gradcam_{tag}_{head}.png"
        plot_sheet(denormalize(x), cams, titles, ok, f"{head} — {tag}", sheet)
        written.append(sheet)
        if save_cams:
            np.savez_compressed(
                out_dir / f"cams_{tag}_{head}.npz",
                paths=pool["path"].to_numpy()[idx].astype(str),
                cams=cams.astype(np.float16),
                pred=pred[idx],
                target=target[idx],
            )
    return written


def make_sheets(
    ckpt: Path,
    splits: Sequence[str] = ("test", "test_xdomain"),
    n: int = 32,
    save_cams: bool = False,
    device: torch.device | None = None,
    out_dir: Path | None = None,
) -> list[Path]:
    """Grad-CAM sheets of a checkpoint for every (split, source) and head; written paths."""
    device = device or pick_device(None)
    model, labels, cfg = load_checkpoint(ckpt, device)
    out_dir = out_dir or REPORTS_DIR / ckpt.parent.name
    out_dir.mkdir(parents=True, exist_ok=True)
    df = load_index(resolve(cfg["data"]["index"]), list(splits))
    written = []
    for (split, source), sub in df.groupby(["split", "source"], observed=True):
        tag = f"{split}_{source}"
        log.info("Grad-CAM %s (%d images)", tag, len(sub))
        written += sheet_for(model, labels, cfg, sub, n, out_dir, tag, save_cams, device)
    log.info("planches écrites dans %s", out_dir)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", help="identifiant de run MLflow (runs/<id>/best.pt)")
    g.add_argument("--checkpoint", type=Path)
    parser.add_argument("--n", type=int, default=32, help="exemples par planche")
    parser.add_argument("--splits", nargs="*", default=["test", "test_xdomain"])
    parser.add_argument("--save-cams", action="store_true")
    parser.add_argument("--device", default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    ckpt = RUNS_DIR / args.run / "best.pt" if args.run else args.checkpoint
    make_sheets(ckpt, args.splits, args.n, args.save_cams, pick_device(args.device))


if __name__ == "__main__":
    main()
