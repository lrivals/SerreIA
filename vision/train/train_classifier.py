"""Train the multi-head classifier (docs/03-classifieur.md §2), tracked in MLflow.

python -m vision.train.train_classifier --config configs/clf_effnet_b0.yaml [--set train.epochs=5]
Smoke test: --subset 512 --limit-batches 5 --device cpu
"""

import argparse
import hashlib
import logging
import math
import random
import subprocess
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader

from vision.datasets.augment import BackgroundPaster, build_transform
from vision.datasets.dataset import (
    IGNORE_INDEX,
    LabelSpace,
    PlantDataset,
    load_index,
    make_sampler,
    stratified_subset,
)
from vision.datasets.taxonomy import load_taxonomy
from vision.eval.metrics import collect_predictions, compute_metrics
from vision.models.multihead import build_model
from vision.train.config import ROOT, apply_overrides, flatten, load_config, resolve

log = logging.getLogger(__name__)

RUNS_DIR = ROOT / "runs"


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def _worker_init(worker_id: int) -> None:
    seed = torch.initial_seed() % 2**32
    random.seed(seed)
    np.random.seed(seed)


def pick_device(name: str | None) -> torch.device:
    if name:
        return torch.device(name)
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def make_loader(
    df: pd.DataFrame,
    labels: LabelSpace,
    cfg: dict,
    *,
    train: bool,
    bg_paster: BackgroundPaster | None = None,
) -> DataLoader:
    d = cfg["data"]
    level = cfg["augment"]["level"] if train else "eval"
    ds = PlantDataset(
        df, labels, build_transform(level, d["size"]), resolve(d["data_dir"]), bg_paster
    )
    return DataLoader(
        ds,
        batch_size=cfg["train"]["batch_size"],
        sampler=make_sampler(df, cfg["seed"]) if train else None,
        num_workers=d["num_workers"],
        pin_memory=torch.cuda.is_available(),
        drop_last=train and len(ds) > cfg["train"]["batch_size"],
        persistent_workers=d["num_workers"] > 0,
        worker_init_fn=_worker_init,
    )


def make_bg_paster(cfg: dict, df: pd.DataFrame) -> BackgroundPaster | None:
    bg = cfg["augment"]["background"]
    if not bg["enabled"]:
        return None
    data_dir = resolve(cfg["data"]["data_dir"])
    masked = [data_dir / p for p in df["mask_path"].dropna()]
    return BackgroundPaster(
        resolve(bg["dir"]),
        extra_leaf_pool=masked,
        p=bg["p"],
        p_multi=bg["p_multi"],
        extra_leaves=tuple(bg["extra_leaves"]),
        feather=bg["feather"],
        harmonize=bg["harmonize"],
    )


class MultiHeadLoss(nn.Module):
    def __init__(self, cfg: dict):
        super().__init__()
        ls = cfg["label_smoothing"]
        self.ce = nn.CrossEntropyLoss(label_smoothing=ls)
        self.ce_classe = nn.CrossEntropyLoss(label_smoothing=ls, ignore_index=IGNORE_INDEX)
        self.w = (cfg["w_espece"], cfg["w_sante"], cfg["w_classe"])

    def forward(self, out: tuple[torch.Tensor, ...], y: torch.Tensor) -> dict[str, torch.Tensor]:
        espece, sante, classe = out
        parts = {"espece": self.ce(espece, y[:, 0]), "sante": self.ce(sante, y[:, 1])}
        # A batch made only of ambiguous classes would give NaN.
        has_classe = (y[:, 2] != IGNORE_INDEX).any()
        parts["classe"] = self.ce_classe(classe, y[:, 2]) if has_classe else classe.sum() * 0.0
        weighted = zip(self.w, ("espece", "sante", "classe"), strict=True)
        parts["total"] = sum(w * parts[k] for w, k in weighted)
        return parts


def warmup_cosine(warmup_steps: int, total_steps: int):
    def f(step: int) -> float:
        if step < warmup_steps:
            return (step + 1) / warmup_steps
        progress = (step - warmup_steps) / max(1, total_steps - warmup_steps)
        return 0.5 * (1.0 + math.cos(math.pi * min(1.0, progress)))

    return f


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_commit() -> str:
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
        return sha + ("-dirty" if dirty.strip() else "")
    except (OSError, subprocess.CalledProcessError):
        return "inconnu"


def save_checkpoint(path: Path, model: nn.Module, cfg: dict, labels: LabelSpace, **extra) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {"model": model.state_dict(), "config": cfg, "labels": labels.to_dict(), **extra}, path
    )


def load_checkpoint(path: Path, device: torch.device | str = "cpu"):
    """(model in eval mode, LabelSpace, config) from a best.pt."""
    ckpt = torch.load(path, map_location=device, weights_only=False)
    labels = LabelSpace.from_dict(ckpt["labels"])
    model = build_model(ckpt["config"], labels.sizes(), pretrained=False)
    model.load_state_dict(ckpt["model"])
    return model.to(device).eval(), labels, ckpt["config"]


def setup_mlflow(cfg: dict) -> None:
    """A plain path is a local SQLite store, artifacts in an `artifacts/` folder next to it.

    (MLflow 3 refuses the old file store `mlruns/` by default.)
    """
    uri, name = cfg["mlflow"]["tracking_uri"], cfg["mlflow"]["experiment"]
    artifacts = None
    if "://" not in uri:
        db = resolve(uri)
        db.parent.mkdir(parents=True, exist_ok=True)
        uri, artifacts = f"sqlite:///{db}", (db.parent / "artifacts").as_uri()
    mlflow.set_tracking_uri(uri)
    if mlflow.get_experiment_by_name(name) is None:
        mlflow.create_experiment(name, artifact_location=artifacts)
    mlflow.set_experiment(name)


def train_one_epoch(
    model, loader, loss_fn, opt, sched, scaler, device, amp_dtype, limit_batches: int
) -> dict[str, float]:
    model.train()
    sums: dict[str, float] = {}
    n = 0
    for b, (x, y) in enumerate(loader):
        if limit_batches and b >= limit_batches:
            break
        x, y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)
        with torch.autocast(device.type, dtype=amp_dtype, enabled=amp_dtype is not None):
            parts = loss_fn(model(x), y)
        opt.zero_grad(set_to_none=True)
        scaler.scale(parts["total"]).backward()
        scaler.step(opt)
        scaler.update()
        sched.step()
        for k, v in parts.items():
            sums[k] = sums.get(k, 0.0) + v.item()
        n += 1
    return {f"loss/{k}": v / max(n, 1) for k, v in sums.items()}


def run(
    cfg: dict,
    device: torch.device,
    subset: int = 0,
    limit_batches: int = 0,
    runs_dir: Path = RUNS_DIR,
) -> Path:
    seed_everything(cfg["seed"])
    taxo = load_taxonomy()
    labels = LabelSpace.from_taxonomy(taxo)
    index_path = resolve(cfg["data"]["index"])
    df = load_index(index_path, ["train", "val"], cfg["data"]["sources"])
    train_df, val_df = (df[df["split"] == s].reset_index(drop=True) for s in ("train", "val"))
    if subset:
        train_df = stratified_subset(train_df, subset, cfg["seed"])
        val_df = stratified_subset(val_df, max(subset // 4, 1), cfg["seed"])
    log.info("train %d images, val %d images", len(train_df), len(val_df))

    train_loader = make_loader(
        train_df, labels, cfg, train=True, bg_paster=make_bg_paster(cfg, train_df)
    )
    val_loader = make_loader(val_df, labels, cfg, train=False)

    model = build_model(cfg, labels.sizes()).to(device)
    o, t = cfg["optim"], cfg["train"]
    opt = torch.optim.AdamW(model.param_groups(o["lr_head"], o["lr_backbone"], o["weight_decay"]))
    steps = min(limit_batches, len(train_loader)) if limit_batches else len(train_loader)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, warmup_cosine(t["warmup_epochs"] * steps, t["epochs"] * steps)
    )
    use_amp = t["amp"] and device.type == "cuda"
    amp_dtype = torch.float16 if use_amp else None
    scaler = torch.amp.GradScaler(device.type, enabled=use_amp)
    loss_fn = MultiHeadLoss(cfg["loss"])

    setup_mlflow(cfg)
    with mlflow.start_run() as active:
        run_dir = runs_dir / active.info.run_id
        mlflow.log_params(flatten(cfg))
        mlflow.log_params(
            {
                "taxonomy_version": taxo.version,
                "index_sha256": file_sha256(index_path),
                "git_commit": git_commit(),
                "n_train": len(train_df),
                "n_val": len(val_df),
                "subset": subset,
                "limit_batches": limit_batches,
                "device": str(device),
            }
        )
        mlflow.log_dict(cfg, "config.yaml")

        select = t["select_metric"]
        best = -math.inf
        for epoch in range(t["epochs"]):
            frozen = epoch < t["freeze_epochs"]
            model.set_backbone_trainable(not frozen)
            losses = train_one_epoch(
                model, train_loader, loss_fn, opt, sched, scaler, device, amp_dtype, limit_batches
            )
            preds = collect_predictions(model, val_loader, device, limit_batches)
            metrics = {f"val/{k}": v for k, v in compute_metrics(preds, labels).items()}
            metrics.update(losses)
            metrics["lr/head"] = opt.param_groups[2]["lr"]
            mlflow.log_metrics(metrics, step=epoch)
            score = metrics[f"val/{select}"]
            log.info(
                "epoch %d%s  loss %.3f  val %s %.4f  classe f1 %.4f",
                epoch,
                " (backbone gelé)" if frozen else "",
                losses.get("loss/total", float("nan")),
                select,
                score,
                metrics.get("val/classe/f1_macro", float("nan")),
            )
            if score > best:
                best = score
                save_checkpoint(
                    run_dir / "best.pt", model, cfg, labels, epoch=epoch, metrics=metrics
                )
        save_checkpoint(run_dir / "last.pt", model, cfg, labels, epoch=t["epochs"] - 1)
        mlflow.log_metric(f"best_val/{select}", best)
        mlflow.log_artifact(str(run_dir / "best.pt"), "checkpoints")
    log.info("run %s, meilleur %s = %.4f -> %s", active.info.run_id, select, best, run_dir)
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--set", nargs="*", default=[], metavar="CLE=VALEUR")
    parser.add_argument("--device", default=None)
    parser.add_argument("--subset", type=int, default=0, help="nb d'images train (smoke test)")
    parser.add_argument("--limit-batches", type=int, default=0, help="batches max par epoch")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    cfg = apply_overrides(load_config(args.config), args.set)
    run(cfg, pick_device(args.device), args.subset, args.limit_batches)


if __name__ == "__main__":
    main()
