"""Train the generic leaf / plant / fruit detector (docs/04-detection-yolo.md §3), in MLflow.

python -m vision.train.train_yolo --config configs/yolo_v8n.yaml [--set yolo.epochs=50]
Smoke test: --set yolo.epochs=1 yolo.fraction=0.05 yolo.batch=4 --device cpu

Ultralytics trains (COCO weights, mosaic, HSV) with an extra LED tint on part of each batch.
Its own MLflow integration is switched off: parameters, per-epoch metrics, mAP and per-class
recall go to the same store as the classifier. Weights: runs/<run_id>/best.pt.
"""

import argparse
import logging
import shutil
from pathlib import Path

import mlflow
import torch
from ultralytics import YOLO
from ultralytics.models.yolo.detect import DetectionTrainer

from vision.datasets.batch_augment import led_tint
from vision.train.config import apply_overrides, flatten, load_config, resolve
from vision.train.train_classifier import (
    RUNS_DIR,
    file_sha256,
    git_commit,
    seed_everything,
    setup_mlflow,
)

log = logging.getLogger(__name__)

ARTIFACT_EXTS = {".png", ".jpg", ".csv", ".yaml"}


def tint_batch(img: torch.Tensor, p: float) -> torch.Tensor:
    """LED tint on a random part (probability p per image) of a [0, 1] float batch."""
    if p <= 0:
        return img
    gate = (torch.rand(len(img), 1, 1, 1, device=img.device) < p).to(img.dtype)
    return torch.lerp(img, led_tint(img), gate)


class SerreTrainer(DetectionTrainer):
    """DetectionTrainer + LED tint, without Ultralytics' MLflow callbacks."""

    led_p = 0.0  # set by make_trainer

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for event, fns in self.callbacks.items():
            self.callbacks[event] = [f for f in fns if "mlflow" not in f.__module__]

    def preprocess_batch(self, batch: dict) -> dict:
        batch = super().preprocess_batch(batch)
        batch["img"] = tint_batch(batch["img"], self.led_p)
        return batch


def make_trainer(led_p: float) -> type[SerreTrainer]:
    return type("SerreTrainer", (SerreTrainer,), {"led_p": led_p})


def log_epoch(trainer) -> None:
    """on_fit_epoch_end: train losses, val metrics and losses, learning rate."""
    metrics = {}
    if trainer.tloss is not None:
        metrics |= trainer.label_loss_items(trainer.tloss, prefix="train")
    metrics |= {k: float(v) for k, v in (trainer.metrics or {}).items()}
    metrics |= {f"lr/{k}": float(v) for k, v in (trainer.lr or {}).items()}
    clean = {k.replace("(", "").replace(")", ""): v for k, v in metrics.items()}
    mlflow.log_metrics(clean, step=trainer.epoch)


def final_metrics(det_metrics) -> dict[str, float]:
    """mAP@0.5, mAP@0.5:0.95, precision, recall, and recall / AP50 per class."""
    box = det_metrics.box
    out = {"test/mAP50": float(box.map50), "test/mAP50-95": float(box.map),
           "test/precision": float(box.mp), "test/recall": float(box.mr)}  # fmt: skip
    for i, c in enumerate(det_metrics.ap_class_index):
        name = det_metrics.names[int(c)]
        out[f"test/recall/{name}"] = float(box.r[i])
        out[f"test/ap50/{name}"] = float(box.ap50[i])
    return out


def run(cfg: dict, device: str | None = None, runs_dir: Path = RUNS_DIR) -> Path:
    seed_everything(cfg["seed"])
    data = resolve(cfg["data"])
    if not data.exists():
        raise FileNotFoundError(f"{data} absent : python -m vision.labeling.build_yolo_dataset")
    setup_mlflow(cfg)
    with mlflow.start_run() as active:
        run_id = active.info.run_id
        run_dir = runs_dir / run_id
        mlflow.log_params(flatten(cfg))
        mlflow.log_params(
            {"data_sha256": file_sha256(data), "git_commit": git_commit(), "device": str(device)}
        )
        mlflow.log_dict(cfg, "config.yaml")

        model = YOLO(cfg["model"])
        model.add_callback("on_fit_epoch_end", log_epoch)
        model.train(
            trainer=make_trainer(cfg["led_tint"]["p"]),
            data=str(data),
            device=device,
            seed=cfg["seed"],
            project=str(runs_dir / "ultralytics"),
            name=run_id,
            exist_ok=True,
            **cfg["yolo"],
        )
        save_dir = Path(model.trainer.save_dir)
        best = save_dir / "weights" / "best.pt"
        run_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(best, run_dir / "best.pt")

        # Final evaluation of best.pt on the held-out test split.
        test = YOLO(str(run_dir / "best.pt")).val(
            data=str(data), split="test", imgsz=cfg["yolo"]["imgsz"], device=device,
            project=str(runs_dir / "ultralytics"), name=f"{run_id}_test", exist_ok=True,
            plots=True,
        )  # fmt: skip
        metrics = final_metrics(test)
        mlflow.log_metrics(metrics)
        for p in save_dir.iterdir():
            if p.suffix in ARTIFACT_EXTS:
                mlflow.log_artifact(str(p), "ultralytics")
        mlflow.log_artifact(str(run_dir / "best.pt"), "checkpoints")
    log.info(
        "run %s : test mAP50 %.3f, mAP50-95 %.3f -> %s",
        run_id, metrics["test/mAP50"], metrics["test/mAP50-95"], run_dir,
    )  # fmt: skip
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--set", nargs="*", default=[], metavar="CLE=VALEUR")
    parser.add_argument("--device", default=None, help="0, cpu… (défaut : Ultralytics choisit)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = apply_overrides(load_config(args.config), args.set)
    run(cfg, args.device)


if __name__ == "__main__":
    main()
