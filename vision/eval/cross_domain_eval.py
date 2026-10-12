"""In-domain (test) and cross-domain (test_xdomain, PlantDoc) evaluation (docs/03 §4).

python -m vision.eval.cross_domain_eval --run <mlflow_run_id>
python -m vision.eval.cross_domain_eval --checkpoint runs/<id>/best.pt [--subset 256]
Writes reports/<run>/metrics.json, summary.md and confusion matrices per source.
"""

import argparse
import json
import logging
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
import torch
from matplotlib.figure import Figure

from vision.datasets.dataset import LabelSpace, load_index, stratified_subset
from vision.eval.metrics import (
    Predictions,
    collect_predictions,
    compute_metrics,
    confusion,
    espece_metrics,
    sante_metrics,
)
from vision.train.config import ROOT, resolve
from vision.train.train_classifier import (
    RUNS_DIR,
    load_checkpoint,
    make_loader,
    pick_device,
    setup_mlflow,
)

log = logging.getLogger(__name__)

REPORTS_DIR = ROOT / "reports"
SUMMARY_KEYS = (
    "sante/recall_anormal",
    "sante/precision_anormal",
    "sante/f1_macro",
    "sante/auroc",
    "sante/ece",
    "espece/accuracy",
    "espece/f1_macro",
    "classe/f1_macro",
    "classe/top3",
    "classe/ece",
)


def common_classes(df: pd.DataFrame, cfg: dict, labels: LabelSpace) -> list[str]:
    """Classes present both in PlantDoc and in the training sources of the run."""
    xdomain = set(df.loc[df["split"] == "test_xdomain", "classe"].astype(str))
    trained = set(
        df.loc[
            (df["split"] == "train") & df["source"].isin(cfg["data"]["sources"]), "classe"
        ].astype(str)
    )
    return sorted(xdomain & trained & set(labels.classes))


def evaluate_split(
    model, labels: LabelSpace, cfg: dict, df: pd.DataFrame, device, restrict=None
) -> tuple[dict, dict[str, Predictions]]:
    """Metrics overall, per source and on ambiguous rows; predictions per source."""
    preds = collect_predictions(model, make_loader(df, labels, cfg, train=False), device)
    out = {"all": compute_metrics(preds, labels, restrict)}
    sources = df["source"].astype(str).to_numpy()
    per_source = {}
    for s in sorted(set(sources)):
        sub = preds.subset(sources == s)
        per_source[s] = sub
        out[s] = compute_metrics(sub, labels, restrict)
    amb = df["ambigu"].to_numpy(bool)
    if amb.any():  # no classe output for them: sante and espece only (docs/02 §2)
        sub = preds.subset(amb)
        out["ambigu"] = {**sante_metrics(sub), **espece_metrics(sub), "n": float(amb.sum())}
    return out, per_source


def plot_confusion(cm: np.ndarray, names: list[str], title: str, path: Path) -> None:
    keep = (cm.sum(0) + cm.sum(1)) > 0  # hide classes absent from this source
    cm, names = cm[keep][:, keep], [n for n, k in zip(names, keep, strict=True) if k]
    norm = cm / np.maximum(cm.sum(1, keepdims=True), 1)
    size = max(4.0, 0.28 * len(names) + 2)
    fig = Figure(figsize=(size, size))
    ax = fig.subplots()
    ax.imshow(norm, cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(len(names)), names, rotation=90, fontsize=6)
    ax.set_yticks(range(len(names)), names, fontsize=6)
    ax.set_xlabel("prédit")
    ax.set_ylabel("réel")
    ax.set_title(title)
    if len(names) <= 6:
        for i in range(len(names)):
            for j in range(len(names)):
                ax.text(j, i, int(cm[i, j]), ha="center", va="center", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150)


def summary_table(results: dict) -> str:
    rows = [(f"{split} / {group}", m) for split, r in results.items() for group, m in r.items()]
    head = "| jeu | n | " + " | ".join(SUMMARY_KEYS) + " |"
    sep = "|---" * (len(SUMMARY_KEYS) + 2) + "|"
    lines = [head, sep]
    for name, m in rows:
        vals = [f"{m[k]:.3f}" if k in m and not np.isnan(m[k]) else "—" for k in SUMMARY_KEYS]
        lines.append(f"| {name} | {int(m.get('n', 0))} | " + " | ".join(vals) + " |")
    return "\n".join(lines) + "\n"


def run_eval(ckpt_path: Path, device, subset: int = 0, out_dir: Path | None = None) -> dict:
    model, labels, cfg = load_checkpoint(ckpt_path, device)
    index = resolve(cfg["data"]["index"])
    full = load_index(index)
    restrict = common_classes(full, cfg, labels)
    splits = {
        "test": full[(full["split"] == "test") & full["source"].isin(cfg["data"]["sources"])],
        "test_xdomain": full[full["split"] == "test_xdomain"],
    }
    run_name = ckpt_path.parent.name
    out_dir = out_dir or REPORTS_DIR / run_name
    out_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    for split, df in splits.items():
        df = df.reset_index(drop=True)
        if subset:
            df = stratified_subset(df, subset, cfg["seed"])
        log.info("%s : %d images", split, len(df))
        # Classe metrics on PlantDoc only make sense on the classes it shares with training.
        r, per_source = evaluate_split(
            model, labels, cfg, df, device, restrict if split == "test_xdomain" else None
        )
        results[split] = r
        for source, preds in per_source.items():
            for head in ("sante", "classe"):
                names = list(labels.vocab(head))
                cm = confusion(preds, head, len(names))
                if not cm.any():
                    continue
                plot_confusion(
                    cm,
                    names,
                    f"{head} — {split} / {source}",
                    out_dir / f"cm_{split}_{source}_{head}.png",
                )

    payload = {
        "checkpoint": str(ckpt_path),
        "config": cfg,
        "taxonomy_version": labels.taxonomy_version,
        "classes_communes_plantdoc": restrict,
        "results": results,
    }
    (out_dir / "metrics.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    (out_dir / "summary.md").write_text(
        f"# Évaluation `{run_name}`\n\n{summary_table(results)}\n"
        f"Classes `classe` sur test_xdomain : {len(restrict)} classes communes avec PlantDoc.\n",
        encoding="utf-8",
    )
    log.info("rapport écrit dans %s", out_dir)
    return payload


def log_to_mlflow(run_id: str, payload: dict, out_dir: Path) -> None:
    setup_mlflow(payload["config"])
    with mlflow.start_run(run_id=run_id):
        for split, r in payload["results"].items():
            for group, m in r.items():
                mlflow.log_metrics({f"{split}/{group}/{k}": v for k, v in m.items()})
        mlflow.log_artifacts(str(out_dir), "eval")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", help="identifiant de run MLflow (runs/<id>/best.pt)")
    g.add_argument("--checkpoint", type=Path)
    parser.add_argument("--device", default=None)
    parser.add_argument("--subset", type=int, default=0, help="nb d'images par jeu (smoke test)")
    parser.add_argument("--no-mlflow", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    ckpt = RUNS_DIR / args.run / "best.pt" if args.run else args.checkpoint
    with torch.inference_mode():
        payload = run_eval(ckpt, pick_device(args.device), args.subset)
    print(summary_table(payload["results"]))
    run_id = args.run or ckpt.parent.name
    if not args.no_mlflow and (RUNS_DIR / run_id).resolve() == ckpt.parent.resolve():
        log_to_mlflow(run_id, payload, REPORTS_DIR / run_id)


if __name__ == "__main__":
    main()
