"""Phase 1 report: A–E ablation table from the evaluations (docs/03 §4, §6).

python -m vision.eval.ablation_report [--registry reports/ablations.json]
Reads reports/<run_id>/metrics.json (written by cross_domain_eval) for every ablation of
the registry and writes reports/phase1.md.
"""

import argparse
import json
import math
from datetime import date
from pathlib import Path

from vision.train.config import ROOT

REPORTS_DIR = ROOT / "reports"
REGISTRY = REPORTS_DIR / "ablations.json"  # {"A_baseline": "<run_id>", ...}
# (column title, split, metric)
COLUMNS = (
    ("F1 sante (test)", "test", "sante/f1_macro"),
    ("F1 classe (test)", "test", "classe/f1_macro"),
    ("rappel anormal (PlantDoc)", "test_xdomain", "sante/recall_anormal"),
    ("F1 sante (PlantDoc)", "test_xdomain", "sante/f1_macro"),
    ("AUROC sante (PlantDoc)", "test_xdomain", "sante/auroc"),
    ("F1 classe (PlantDoc)", "test_xdomain", "classe/f1_macro"),
    ("top-3 classe (PlantDoc)", "test_xdomain", "classe/top3"),
    ("ECE sante (PlantDoc)", "test_xdomain", "sante/ece"),
)
# Exit criteria of phase 1 (docs/03 §6): (label, split, metric, minimum)
CRITERIA = (
    ("F1 sante in-domain ≥ 0,97", "test", "sante/f1_macro", 0.97),
    ("rappel « anormal » PlantDoc ≥ 0,80", "test_xdomain", "sante/recall_anormal", 0.80),
)


def load_registry(path: Path = REGISTRY) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_registry(registry: dict[str, str], path: Path = REGISTRY) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _metric(results: dict, split: str, metric: str) -> float:
    return results.get(split, {}).get("all", {}).get(metric, math.nan)


def _fmt(v: float) -> str:
    return "—" if math.isnan(v) else f"{v:.3f}"


def phase1_markdown(runs: dict[str, str], reports_dir: Path = REPORTS_DIR) -> str:
    rows, missing = [], []
    for name, run_id in sorted(runs.items()):
        path = reports_dir / run_id / "metrics.json"
        if not path.exists():
            missing.append(f"{name} ({run_id})")
            continue
        rows.append((name, run_id, json.loads(path.read_text(encoding="utf-8"))["results"]))

    lines = [
        "# Phase 1 — ablations du classifieur",
        "",
        f"Généré le {date.today():%d/%m/%Y} par `python -m vision.eval.ablation_report` "
        "(voir [docs/03-classifieur.md](../docs/03-classifieur.md) §4).",
        "",
        "| ablation | run | " + " | ".join(c[0] for c in COLUMNS) + " |",
        "|---|---" + "|---" * len(COLUMNS) + "|",
    ]
    for name, run_id, res in rows:
        vals = [_fmt(_metric(res, split, m)) for _, split, m in COLUMNS]
        lines.append(f"| {name} | `{run_id[:8]}` | " + " | ".join(vals) + " |")

    lines += ["", "## Critères de sortie (§6)", ""]
    for name, _, res in rows:
        checks = []
        for label, split, metric, minimum in CRITERIA:
            v = _metric(res, split, metric)
            ok = not math.isnan(v) and v >= minimum
            checks.append(f"{'✅' if ok else '❌'} {label} ({_fmt(v)})")
        lines.append(f"- **{name}** : " + " ; ".join(checks))
    if missing:
        lines += ["", "Évaluations manquantes : " + ", ".join(missing) + "."]
    lines += [
        "",
        "Détail par run (matrices de confusion, planches Grad-CAM) : `reports/<run_id>/` "
        "(non versionné ; `make harvest` depuis Colab).",
        "",
    ]
    return "\n".join(lines)


def write_phase1_report(
    runs: dict[str, str] | None = None,
    reports_dir: Path = REPORTS_DIR,
    out: Path | None = None,
) -> Path:
    runs = load_registry(reports_dir / "ablations.json") if runs is None else runs
    out = out or reports_dir / "phase1.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(phase1_markdown(runs, reports_dir), encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    args = parser.parse_args()
    out = write_phase1_report(load_registry(args.registry), args.registry.parent)
    print(out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
