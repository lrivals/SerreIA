"""Generator of the phase 1 notebooks (notebooks/*.ipynb), docs/03-classifieur.md §7.

python -m tools.notebooks.build           # rewrites notebooks/
python -m tools.notebooks.build --check   # exit 1 if a notebook differs from the generator

Fixed structure: title + Colab badge, `parameters` cell (papermill compatible), setup cell
(repository and data, docs/data-drive.md), body, summary. The JSON is written without
outputs, sorted and indented like Jupyter saves it. Cells only call repository code.
"""

import argparse
import json
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NB_DIR = ROOT / "notebooks"
COLAB_URL = "https://colab.research.google.com/github/lrivals/SerreIA/blob/main/notebooks"
DATA = ["index", "plantvillage", "ccmt", "plantdoc"]


def _lines(text: str) -> list[str]:
    lines = textwrap.dedent(text).strip("\n").split("\n")
    return [line + "\n" for line in lines[:-1]] + [lines[-1]]


def md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": _lines(text)}


def code(text: str, tags: list[str] | None = None) -> dict:
    meta = {"tags": tags} if tags else {}
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": meta,
        "outputs": [],
        "source": _lines(text),
    }


def notebook(cells: list[dict], gpu: bool) -> dict:
    meta = {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python"},
    }
    if gpu:
        meta["accelerator"] = "GPU"
        meta["colab"] = {"gpuType": "T4", "provenance": []}
    return {"cells": cells, "metadata": meta, "nbformat": 4, "nbformat_minor": 5}


def dumps(nb: dict) -> str:
    """Jupyter's save format: sorted JSON, indent 1, final newline."""
    return json.dumps(nb, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


# ------------------------------------------------------------------------- common cells

SETUP = """
# Environnement (PC et Colab) : dépôt, données, sorties (docs/data-drive.md).
# PC : rien n'est installé ; un jeu absent est récupéré du Drive par rclone, sinon la cellule
# s'arrête avec la commande à lancer. Colab : clone du dépôt à REV, installation, données via
# le Drive monté (archives MyDrive/SerreIA/data/*.tar), sorties précédentes restaurées.
import logging
import os
import subprocess
import sys
from pathlib import Path

DRIVE_DIR = "/content/drive/MyDrive/SerreIA"  # Colab : data/*.tar et runs/ ; None : pas de Drive
REPO_URL = "https://github.com/lrivals/SerreIA.git"
REV = "main"
COLAB = "google.colab" in sys.modules

if COLAB:
    ROOT = Path("/content/SerreIA")
    if not ROOT.exists():
        subprocess.run(["git", "clone", "-q", REPO_URL, str(ROOT)], check=True)
    subprocess.run(["git", "-C", str(ROOT), "fetch", "-q", "origin", REV], check=True)
    subprocess.run(["git", "-C", str(ROOT), "checkout", "-q", "--detach", "FETCH_HEAD"], check=True)
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "-e", f"{ROOT}[vision]"], check=True
    )
else:
    ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / ".git").exists())
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", force=True)

from tools.notebooks import drive_data  # noqa: E402

if COLAB and DRIVE_DIR:
    drive_data.mount_drive()
    drive_data.restore_all(DRIVE_DIR)
drive_data.ensure(DATASETS, DRIVE_DIR if COLAB else None)

# Colab : tous les cœurs pour le chargement, base MLflow séparée de celle du PC.
ENV_SET = (
    [f"data.num_workers={os.cpu_count()}", f"mlflow.tracking_uri={drive_data.COLAB_MLFLOW}"]
    if COLAB
    else []
)
"""

BACKGROUNDS = """
def ensure_backgrounds(cfg):
    \"\"\"Fonds de serre requis par le remplacement de fond (docs/03 §3.2).\"\"\"
    if not cfg["augment"]["background"]["enabled"]:
        return
    try:
        drive_data.ensure(["backgrounds"], DRIVE_DIR if COLAB else None)
    except RuntimeError as e:
        raise RuntimeError(
            f"{e}\\nRemplir data/backgrounds/ puis `tools/get_datasets.sh push backgrounds`, "
            'ou SET = ["augment.background.enabled=false"].'
        ) from None
"""


def header(name: str, title: str, intro: str, gpu: bool) -> dict:
    badge = f"[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)]({COLAB_URL}/{name})"
    gpu_note = (
        "\n\nSur Colab : *Exécution → Modifier le type d'exécution → GPU (T4)*." if gpu else ""
    )
    return md(f"# {title}\n\n{badge}\n\n{textwrap.dedent(intro).strip()}{gpu_note}")


@dataclass
class Notebook:
    name: str
    title: str
    intro: str
    params: str
    body: list[dict]
    gpu: bool = False
    extra_setup: list[str] = field(default_factory=list)

    def build(self) -> dict:
        cells = [
            header(self.name, self.title, self.intro, self.gpu),
            md("## Paramètres"),
            code(self.params, tags=["parameters"]),
            md("## Environnement"),
            code(SETUP),
            *[code(c) for c in self.extra_setup],
            *self.body,
        ]
        stem = self.name.split("_")[0]
        for i, cell in enumerate(cells):  # stable ids: regenerating changes nothing
            cell["id"] = f"nb{stem}-{i:02d}"
        return notebook(cells, self.gpu)


# ---------------------------------------------------------------------------- 01 données

NB_DONNEES = Notebook(
    name="01_donnees.ipynb",
    title="01 — Données de la phase 1",
    intro="""
    Exploration de `data/index.parquet` (docs/02-donnees.md) : effectifs par source, split et
    classe, groupes contradictoires écartés, exemples d'images, augmentations fortes et
    remplacement de fond (docs/03-classifieur.md §3). Pas de GPU nécessaire.
    """,
    params="""
    DATASETS = ["index", "plantvillage", "ccmt", "plantdoc"]
    N_EXAMPLES = 8  # images par source / variantes d'augmentation
    SEED = 0
    """,
    body=[
        md("## Index et splits"),
        code("""
        import pandas as pd
        from IPython.display import display

        from vision.datasets.build_index import DATA_DIR, INDEX_NAME
        from vision.datasets.dataset import load_index

        raw = pd.read_parquet(DATA_DIR / INDEX_NAME)
        df = load_index(DATA_DIR / INDEX_NAME)
        print(f"{len(raw)} images indexées, {len(raw) - len(df)} écartées (groupes contradictoires)")
        print(f"{df['espece'].nunique()} espèces, {df['classe'].nunique()} classes, "
              f"{df.loc[df['ambigu'], 'classe'].nunique()} ambiguës")
        display(pd.crosstab(df["source"], df["split"], margins=True))
        """),
        code("""
        per_class = pd.crosstab(df["classe"], df["split"])
        per_class["total"] = per_class.sum(axis=1)
        display(per_class.sort_values("total"))
        """),
        md("## Exemples par source"),
        code("""
        import matplotlib.pyplot as plt

        from vision.datasets.dataset import read_rgb

        for source, sub in df.groupby("source", observed=True):
            rows = sub.sample(min(N_EXAMPLES, len(sub)), random_state=SEED)
            fig, axes = plt.subplots(1, len(rows), figsize=(2.2 * len(rows), 2.6))
            for ax, (_, r) in zip(axes, rows.iterrows()):
                ax.imshow(read_rgb(DATA_DIR / r["path"]))
                ax.set_title(r["classe"].split("/", 1)[1], fontsize=7)
                ax.axis("off")
            fig.suptitle(source)
            plt.show()
        """),
        md("## Augmentations fortes (§3.1)"),
        code("""
        import random

        from vision.datasets.augment import build_transform
        from vision.eval.gradcam import denormalize

        random.seed(SEED)
        r = df[df["source"] == "plantvillage"].sample(1, random_state=SEED).iloc[0]
        img = read_rgb(DATA_DIR / r["path"])
        strong = build_transform("strong", 224)
        fig, axes = plt.subplots(1, N_EXAMPLES + 1, figsize=(2.2 * (N_EXAMPLES + 1), 2.4))
        axes[0].imshow(img)
        axes[0].set_title("original", fontsize=8)
        for ax in axes[1:]:
            ax.imshow(denormalize(strong(image=img)["image"][None])[0])
        for ax in axes:
            ax.axis("off")
        plt.show()
        """),
        md("""
        ## Remplacement de fond (§3.2)

        Nécessite `data/backgrounds/` (jeu `backgrounds`, voir docs/data-drive.md) ; sinon la
        cellule l'indique et ne fait rien.
        """),
        code("""
        from vision.datasets.augment import BackgroundPaster

        if drive_data.ready("backgrounds"):
            masked = df[df["mask_path"].notna()].sample(N_EXAMPLES, random_state=SEED)
            pool = [DATA_DIR / p for p in masked["mask_path"]]
            paster = BackgroundPaster(DATA_DIR / "backgrounds", pool, p=1.0, p_multi=0.5)
            fig, axes = plt.subplots(2, N_EXAMPLES, figsize=(2.2 * N_EXAMPLES, 4.6))
            for k, (_, r) in enumerate(masked.iterrows()):
                img = read_rgb(DATA_DIR / r["path"])
                axes[0, k].imshow(img)
                axes[1, k].imshow(paster(img, read_rgb(DATA_DIR / r["mask_path"])))
            for ax in axes.ravel():
                ax.axis("off")
            plt.show()
        else:
            print("data/backgrounds/ absent : aperçu du remplacement de fond ignoré.")
        """),
    ],
)

# ------------------------------------------------------------------------ 02 entraînement

TRAIN_PARAMS = """
CONFIG = "configs/clf_effnet_b0.yaml"
SET = []  # surcharges « cle=valeur », ex. ["train.epochs=5", "augment.background.enabled=false"]
SUBSET = 0  # nb d'images train (0 : tout) ; smoke test : 512
LIMIT_BATCHES = 0  # batches max par epoch (0 : tous) ; smoke test : 5
DEVICE = None  # None : cuda si disponible
GRADCAM_N = 32  # exemples par planche
ONNX_N = 256  # images val pour la vérification ONNX
DATASETS = ["index", "plantvillage", "ccmt", "plantdoc"]
"""

EVAL_CELLS = [
    md("## Évaluation in-domain et cross-domain (§4)"),
    code("""
    import torch
    from IPython.display import Image, Markdown, display

    from vision.eval.cross_domain_eval import REPORTS_DIR, log_to_mlflow, run_eval, summary_table

    CKPT = ROOT / "runs" / RUN_ID / "best.pt"
    device = pick_device(DEVICE)
    with torch.inference_mode():
        payload = run_eval(CKPT, device, SUBSET)
    OUT = REPORTS_DIR / RUN_ID
    log_to_mlflow(RUN_ID, payload, OUT)
    display(Markdown(summary_table(payload["results"])))
    """),
    code("""
    for png in sorted(OUT.glob("cm_*_sante.png")):
        print(png.name)
        display(Image(filename=png, width=360))
    """),
    md("## Grad-CAM (§5)"),
    code("""
    from vision.eval.gradcam import make_sheets

    sheets = make_sheets(CKPT, n=GRADCAM_N, save_cams=True, device=device)
    for png in sheets:
        if png.name.endswith("_sante.png"):
            print(png.name)
            display(Image(filename=png))
    """),
    md("## Export ONNX (§6 : écart < 0,5 point)"),
    code("""
    from vision.export.to_onnx import export_and_check

    onnx_res = export_and_check(CKPT, ONNX_N)
    worst = onnx_res["worst_disagree_pts"]
    print(f"écart max {worst:.2f} pt : {'OK' if worst < 0.5 else 'ÉCHEC'}")
    drive_data.sync_all(DRIVE_DIR)
    """),
]

NB_ENTRAINEMENT = Notebook(
    name="02_entrainement.ipynb",
    title="02 — Entraînement du classifieur",
    intro="""
    Un run complet (docs/03-classifieur.md §2) : entraînement suivi dans MLflow, puis
    évaluation `test` / `test_xdomain`, planches Grad-CAM et export ONNX vérifié. Sur Colab,
    `runs/`, `reports/` et `mlruns/colab/` sont copiés sur le Drive toutes les 10 min ; sur le
    PC : `make harvest`.
    """,
    params=TRAIN_PARAMS,
    gpu=True,
    extra_setup=[BACKGROUNDS],
    body=[
        md("## Configuration"),
        code("""
        import yaml

        from vision.train.config import apply_overrides, load_config
        from vision.train.train_classifier import pick_device, run

        cfg = apply_overrides(load_config(ROOT / CONFIG), ENV_SET + SET)
        ensure_backgrounds(cfg)
        print(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
        """),
        md("## Entraînement"),
        code("""
        with drive_data.PeriodicSync(drive_data.OUTPUTS, DRIVE_DIR):
            run_dir = run(cfg, pick_device(DEVICE), SUBSET, LIMIT_BATCHES)
        RUN_ID = run_dir.name
        print("RUN_ID =", RUN_ID)
        """),
        *EVAL_CELLS,
        md("""
        ## Résumé

        Checkpoint : `runs/<RUN_ID>/best.pt` ; rapport : `reports/<RUN_ID>/` (`summary.md`,
        matrices, planches) ; MLflow : `mlflow ui --backend-store-uri sqlite:///mlruns/mlflow.db`
        (PC) ou `mlruns/colab/mlflow.db` (récupéré par `make harvest`).
        """),
    ],
)

# ------------------------------------------------------------------------- 03 évaluation

NB_EVALUATION = Notebook(
    name="03_evaluation.ipynb",
    title="03 — Évaluation d'un run",
    intro="""
    Évaluation d'un checkpoint existant (docs/03-classifieur.md §4–§6) : métriques par
    source, matrices de confusion, Grad-CAM, export ONNX. `RUN_ID = None` prend le dernier
    run de `runs/` (sur Colab, restauré depuis le Drive).
    """,
    params="""
    RUN_ID = None  # identifiant MLflow (dossier runs/<RUN_ID>/) ; None : le plus récent
    SUBSET = 0  # nb d'images par jeu (0 : tout)
    DEVICE = None
    GRADCAM_N = 32
    ONNX_N = 256
    DATASETS = ["index", "plantvillage", "ccmt", "plantdoc"]
    """,
    gpu=True,
    body=[
        md("## Run"),
        code("""
        from vision.train.train_classifier import pick_device

        if RUN_ID is None:
            ckpts = sorted((ROOT / "runs").glob("*/best.pt"), key=lambda p: p.stat().st_mtime)
            if not ckpts:
                raise FileNotFoundError("aucun runs/*/best.pt : lancer 02_entrainement")
            RUN_ID = ckpts[-1].parent.name
        print("RUN_ID =", RUN_ID)
        """),
        *EVAL_CELLS,
        code("""
        for png in sorted(OUT.glob("cm_*_classe.png")):
            print(png.name)
            display(Image(filename=png))
        """),
    ],
)

# -------------------------------------------------------------------------- 04 ablations

NB_ABLATIONS = Notebook(
    name="04_ablations.ipynb",
    title="04 — Ablations A–E",
    intro="""
    Les cinq variantes de docs/03-classifieur.md §4 (`configs/ablations/`), entraînées puis
    évaluées l'une après l'autre ; tableau final dans `reports/phase1.md`. Les runs terminés
    sont enregistrés dans `reports/ablations.json` : une session interrompue reprend à
    l'ablation suivante (retirer une entrée pour la relancer). Compter plusieurs heures par
    ablation sur un T4.
    """,
    params="""
    ABLATIONS = ["A_baseline", "B_strong_aug", "C_background", "D_ccmt", "E_convnext"]
    SET = []  # surcharges appliquées à toutes les ablations
    SUBSET = 0
    LIMIT_BATCHES = 0
    DEVICE = None
    DATASETS = ["index", "plantvillage", "ccmt", "plantdoc"]
    """,
    gpu=True,
    extra_setup=[BACKGROUNDS],
    body=[
        md("## Entraînement et évaluation de chaque ablation"),
        code("""
        import torch

        from vision.eval.ablation_report import load_registry, save_registry
        from vision.eval.cross_domain_eval import REPORTS_DIR, log_to_mlflow, run_eval
        from vision.train.config import apply_overrides, load_config
        from vision.train.train_classifier import pick_device, run

        device = pick_device(DEVICE)
        registry = load_registry()
        for name in ABLATIONS:
            done = registry.get(name)
            if done and (REPORTS_DIR / done / "metrics.json").exists():
                print(f"{name} : déjà fait ({done})")
                continue
            cfg = apply_overrides(
                load_config(ROOT / "configs" / "ablations" / f"{name}.yaml"), ENV_SET + SET
            )
            ensure_backgrounds(cfg)
            print(f"=== {name} ===")
            with drive_data.PeriodicSync(drive_data.OUTPUTS, DRIVE_DIR):
                run_id = run(cfg, device, SUBSET, LIMIT_BATCHES).name
                with torch.inference_mode():
                    payload = run_eval(ROOT / "runs" / run_id / "best.pt", device, SUBSET)
                log_to_mlflow(run_id, payload, REPORTS_DIR / run_id)
                registry[name] = run_id
                save_registry(registry)
        """),
        md("## Rapport `reports/phase1.md`"),
        code("""
        from IPython.display import Markdown, display

        from vision.eval.ablation_report import write_phase1_report

        report = write_phase1_report({k: v for k, v in registry.items() if k in ABLATIONS})
        drive_data.sync_all(DRIVE_DIR)
        display(Markdown(report.read_text(encoding="utf-8")))
        """),
    ],
)

NOTEBOOKS = [NB_DONNEES, NB_ENTRAINEMENT, NB_EVALUATION, NB_ABLATIONS]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="vérifie sans écrire")
    args = parser.parse_args()
    NB_DIR.mkdir(exist_ok=True)
    stale = []
    for nb in NOTEBOOKS:
        path = NB_DIR / nb.name
        text = dumps(nb.build())
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == text:
            continue
        if args.check:
            stale.append(nb.name)
        else:
            path.write_text(text, encoding="utf-8")
            print(f"écrit : {path.relative_to(ROOT)}")
    if stale:
        print("notebooks à régénérer (python -m tools.notebooks.build) : " + ", ".join(stale))
        sys.exit(1)


if __name__ == "__main__":
    main()
