"""Accuracy of the classifier on two backends and their gap (docs/05 §2 and §5).

    # INT8 vs float, on the PC (Hailo Docker, quantized emulation) or on the Pi (HEF)
    python -m vision.export.evaluate_backend --reference onnx:edge/models/v1 \\
        --candidate har:edge/models/v1/clf.q.har          # or hailo:edge/models/v1
    # Deployment gate: new model vs current one on the frozen greenhouse set
    python -m vision.export.evaluate_backend --reference onnx:edge/models/current \\
        --candidate onnx:edge/models/v2 --sources serre --splits gel --max-drop 0

Backends: `onnx:<bundle>`, `hailo:<bundle>` (HEF of the manifest, on the Pi) or
`har:<file.q.har>` (DFC emulator). Labels come from the reference bundle. Accuracy per
head over the rows whose label the model knows; verdict: no head of the candidate loses
more than --max-drop points (2 for HEF vs ONNX, 0 for the regression gate). Exit code 1
on failure, for deployment scripts.
"""

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from edge.vision.backends import Backend, HailoBackend, HarEmulatorBackend, OnnxBackend
from edge.vision.bundle import load_manifest
from edge.vision.classifier import HEADS, EdgeClassifier
from vision.datasets.build_index import DATA_DIR, INDEX_NAME
from vision.datasets.dataset import load_index, read_rgb, stratified_subset

log = logging.getLogger(__name__)


def make_backend(spec: str) -> tuple[Backend, Path | None]:
    """'kind:path' -> (backend, bundle directory or None)."""
    kind, _, arg = spec.partition(":")
    path = Path(arg)
    if kind == "har":
        return HarEmulatorBackend(path), None
    entry = load_manifest(path)["classifieur"]
    if kind == "onnx":
        return OnnxBackend(path / entry["onnx"]), path
    if kind == "hailo":
        return HailoBackend(path / entry["hef"]), path
    raise ValueError(f"backend inconnu {spec!r} (onnx:, hailo:, har:)")


def predict(clf: EdgeClassifier, paths: Sequence[Path], batch: int = 32) -> pd.DataFrame:
    rows = []
    for i in range(0, len(paths), batch):
        rows += clf([read_rgb(p) for p in paths[i : i + batch]])
    return pd.DataFrame(rows)


def accuracy(pred: pd.DataFrame, truth: pd.DataFrame, vocab: dict) -> dict[str, float]:
    """Per head accuracy (%) over the rows whose true label is in the model's vocabulary."""
    out = {}
    for h in HEADS:
        known = truth[h].astype(str).isin(vocab[h]).to_numpy()
        hit = pred[h].to_numpy()[known] == truth[h].astype(str).to_numpy()[known]
        out[h] = 100.0 * hit.mean() if known.any() else float("nan")
    return out


def compare(ref: EdgeClassifier, cand: EdgeClassifier, df: pd.DataFrame, data_dir: Path) -> dict:
    paths = [data_dir / p for p in df["path"]]
    p_ref, p_cand = predict(ref, paths), predict(cand, paths)
    a_ref, a_cand = accuracy(p_ref, df, ref.vocab), accuracy(p_cand, df, ref.vocab)
    agree = {h: 100.0 * float((p_ref[h] == p_cand[h]).mean()) for h in HEADS}
    return {
        "n": len(df),
        "reference": a_ref,
        "candidat": a_cand,
        "ecart_pts": {h: a_cand[h] - a_ref[h] for h in HEADS},
        "accord_pts": agree,
    }


def verdict(results: dict[str, dict], max_drop: float) -> bool:
    drops = [-d for r in results.values() for d in r["ecart_pts"].values() if not np.isnan(d)]
    return all(d <= max_drop for d in drops)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reference", required=True, help="onnx:<bundle> en général")
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--splits", nargs="+", default=["test", "test_xdomain"])
    parser.add_argument("--sources", nargs="+", default=None)
    parser.add_argument("--n", type=int, default=0, help="sous-échantillon stratifié par split")
    parser.add_argument("--max-drop", type=float, default=2.0, help="perte max en points")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--out", type=Path, default=None, help="rapport JSON")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    ref_backend, bundle = make_backend(args.reference)
    if bundle is None:
        raise SystemExit("la référence doit être un bundle (onnx: ou hailo:) : il porte les labels")
    labels = load_manifest(bundle)["classifieur"]["labels"]
    ref = EdgeClassifier(ref_backend, labels)
    cand = EdgeClassifier(make_backend(args.candidate)[0], labels)

    index = load_index(args.data_dir / INDEX_NAME, None, args.sources)
    results = {}
    for split in args.splits:
        df = index[index["split"] == split]
        if df.empty:
            log.warning("split %s vide", split)
            continue
        if args.n:
            df = stratified_subset(df, args.n, seed=0)
        results[split] = compare(ref, cand, df.reset_index(drop=True), args.data_dir)
        r = results[split]
        for h in HEADS:
            print(
                f"{split:14s} {h:7s} réf {r['reference'][h]:6.2f}  cand {r['candidat'][h]:6.2f}"
                f"  écart {r['ecart_pts'][h]:+6.2f} pt  accord {r['accord_pts'][h]:6.2f} %"
            )
    ok = bool(results) and verdict(results, args.max_drop)
    print(f"perte max autorisée {args.max_drop:g} pt : {'OK' if ok else 'ÉCHEC'}")
    if args.out:
        args.out.write_text(json.dumps({"resultats": results, "ok": ok}, indent=1))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
