"""Classifier metrics shared by training (val) and evaluation (docs/03 §4)."""

from collections.abc import Collection
from dataclasses import dataclass

import numpy as np
import torch
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from torch.utils.data import DataLoader

from vision.datasets.dataset import HEADS, IGNORE_INDEX, LabelSpace

ANORMAL = 1  # index of "anormal" in LabelSpace.sante


@dataclass
class Predictions:
    logits: dict[str, np.ndarray]  # head -> (n, k) float32
    targets: np.ndarray  # (n, 3) int64, HEADS order

    def probs(self, head: str) -> np.ndarray:
        return torch.from_numpy(self.logits[head]).float().softmax(1).numpy()

    def target(self, head: str) -> np.ndarray:
        return self.targets[:, HEADS.index(head)]

    def subset(self, mask: np.ndarray) -> "Predictions":
        return Predictions({h: v[mask] for h, v in self.logits.items()}, self.targets[mask])


@torch.no_grad()
def collect_predictions(
    model: torch.nn.Module, loader: DataLoader, device: torch.device, limit_batches: int = 0
) -> Predictions:
    model.eval()
    logits = {h: [] for h in HEADS}
    targets = []
    for b, (x, y) in enumerate(loader):
        if limit_batches and b >= limit_batches:
            break
        out = model(x.to(device, non_blocking=True))
        for h, o in zip(HEADS, out, strict=True):
            logits[h].append(o.float().cpu().numpy())
        targets.append(y.numpy())
    return Predictions({h: np.concatenate(v) for h, v in logits.items()}, np.concatenate(targets))


def expected_calibration_error(probs: np.ndarray, target: np.ndarray, n_bins: int = 15) -> float:
    conf = probs.max(1)
    correct = probs.argmax(1) == target
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        in_bin = (conf > lo) & (conf <= hi)
        if in_bin.any():
            ece += in_bin.mean() * abs(correct[in_bin].mean() - conf[in_bin].mean())
    return float(ece)


def top_k_accuracy(probs: np.ndarray, target: np.ndarray, k: int) -> float:
    top = np.argsort(-probs, axis=1)[:, :k]
    return float((top == target[:, None]).any(1).mean())


def sante_metrics(p: Predictions) -> dict[str, float]:
    y = p.target("sante")
    probs = p.probs("sante")
    pred = probs.argmax(1)
    out = {
        "sante/recall_anormal": recall_score(y, pred, pos_label=ANORMAL, zero_division=0),
        "sante/precision_anormal": precision_score(y, pred, pos_label=ANORMAL, zero_division=0),
        "sante/f1_anormal": f1_score(y, pred, pos_label=ANORMAL, zero_division=0),
        "sante/f1_macro": f1_score(y, pred, average="macro", labels=[0, 1], zero_division=0),
        "sante/ece": expected_calibration_error(probs, y),
    }
    out["sante/auroc"] = (
        roc_auc_score(y, probs[:, ANORMAL]) if len(np.unique(y)) == 2 else float("nan")
    )
    return {k: float(v) for k, v in out.items()}


def espece_metrics(p: Predictions) -> dict[str, float]:
    y = p.target("espece")
    probs = p.probs("espece")
    pred = probs.argmax(1)
    return {
        "espece/accuracy": float(accuracy_score(y, pred)),
        "espece/f1_macro": float(f1_score(y, pred, average="macro", labels=np.unique(y))),
        "espece/ece": expected_calibration_error(probs, y),
    }


def classe_metrics(
    p: Predictions, labels: LabelSpace, restrict_to: Collection[str] | None = None
) -> dict[str, float]:
    """Macro F1 / top-k over non-ambiguous rows, optionally only the given classes.

    The macro average only covers classes present in the targets, so that a test set
    with fewer classes (PlantDoc) is not penalised for the classes it does not contain.
    """
    y = p.target("classe")
    keep = y != IGNORE_INDEX
    if restrict_to is not None:
        allowed = [labels.classes.index(c) for c in restrict_to if c in labels.classes]
        keep &= np.isin(y, allowed)
    if not keep.any():
        return {}
    y = y[keep]
    probs = p.probs("classe")[keep]
    pred = probs.argmax(1)
    return {
        "classe/f1_macro": float(f1_score(y, pred, average="macro", labels=np.unique(y))),
        "classe/accuracy": float(accuracy_score(y, pred)),
        "classe/top3": top_k_accuracy(probs, y, 3),
        "classe/ece": expected_calibration_error(probs, y),
        "classe/n": float(keep.sum()),
    }


def compute_metrics(
    p: Predictions, labels: LabelSpace, classe_restrict: Collection[str] | None = None
) -> dict[str, float]:
    return {
        **sante_metrics(p),
        **espece_metrics(p),
        **classe_metrics(p, labels, classe_restrict),
        "n": float(len(p.targets)),
    }


def confusion(p: Predictions, head: str, n_classes: int) -> np.ndarray:
    y = p.target(head)
    keep = y != IGNORE_INDEX
    pred = p.logits[head].argmax(1)
    if not keep.any():  # e.g. a source made only of ambiguous classes
        return np.zeros((n_classes, n_classes), dtype=np.int64)
    return confusion_matrix(y[keep], pred[keep], labels=list(range(n_classes)))
