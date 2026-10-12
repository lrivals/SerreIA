"""ONNX export of the classifier, checked against PyTorch (docs/03 §1, docs/05 §2).

python -m vision.export.to_onnx --run <mlflow_run_id> [--n 256]
Fixed input 1x3xSxS, opset 17, outputs espece / sante / classe in that order.
"""

import argparse
import logging
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import torch
from torch import nn

from vision.datasets.dataset import HEADS, load_index, stratified_subset
from vision.train.config import resolve
from vision.train.train_classifier import RUNS_DIR, load_checkpoint, make_loader

log = logging.getLogger(__name__)

OPSET = 17


def export_onnx(model: nn.Module, path: Path, size: int) -> None:
    model = model.cpu().eval()
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        model,
        (torch.zeros(1, 3, size, size),),
        str(path),
        input_names=["image"],
        output_names=list(HEADS),
        opset_version=OPSET,
        dynamo=False,
    )
    onnx.checker.check_model(onnx.load(str(path)))


@torch.no_grad()
def compare(model: nn.Module, path: Path, batches) -> dict[str, float]:
    """Max |logit| gap and argmax agreement (in points) per head, ONNX vs PyTorch."""
    model = model.cpu().eval()
    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    gap = dict.fromkeys(HEADS, 0.0)
    agree = dict.fromkeys(HEADS, 0)
    n = 0
    for x in batches:
        for img in x:  # fixed batch size of 1 in the exported graph
            ref = model(img[None])
            out = sess.run(None, {"image": img[None].numpy()})
            for h, r, o in zip(HEADS, ref, out, strict=True):
                gap[h] = max(gap[h], float(np.abs(r.numpy() - o).max()))
                agree[h] += int(r.argmax(1).item() == o.argmax(1).item())
            n += 1
    res = {f"{h}/max_abs_gap": gap[h] for h in HEADS}
    res.update({f"{h}/disagree_pts": 100.0 * (1 - agree[h] / max(n, 1)) for h in HEADS})
    res["n"] = float(n)
    return res


def export_and_check(ckpt: Path, n: int = 256, out: Path | None = None) -> dict[str, float]:
    """Export of a checkpoint (default <run>/model.onnx) and comparison on n val images.

    `worst_disagree_pts` is compared to the 0.5 point criterion of docs/03 §6.
    """
    model, labels, cfg = load_checkpoint(ckpt)
    out = out or ckpt.parent / "model.onnx"
    export_onnx(model, out, cfg["data"]["size"])
    log.info("export : %s", out)

    df = load_index(resolve(cfg["data"]["index"]), ["val"], cfg["data"]["sources"])
    df = stratified_subset(df, n, cfg["seed"])
    loader = make_loader(
        df, labels, {**cfg, "data": {**cfg["data"], "num_workers": 0}}, train=False
    )
    res = compare(model, out, (x for x, _ in loader))
    res["worst_disagree_pts"] = max(res[f"{h}/disagree_pts"] for h in HEADS)
    return res


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", help="identifiant de run MLflow (runs/<id>/best.pt)")
    g.add_argument("--checkpoint", type=Path)
    parser.add_argument("--out", type=Path, default=None, help="défaut : <run>/model.onnx")
    parser.add_argument("--n", type=int, default=256, help="images val pour la comparaison")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    ckpt = RUNS_DIR / args.run / "best.pt" if args.run else args.checkpoint
    res = export_and_check(ckpt, args.n, args.out)
    for k, v in res.items():
        print(f"{k:24s} {v:.6f}")
    worst = res["worst_disagree_pts"]
    verdict = "OK" if worst < 0.5 else "ÉCHEC"
    print(f"écart max {worst:.2f} pt (critère < 0,5 pt) : {verdict}")


if __name__ == "__main__":
    main()
