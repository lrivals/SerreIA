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


GPU_CHECK = """
# Entraînement, évaluation et Grad-CAM tournent sur le GPU, augmentations comprises.
import torch

if torch.cuda.is_available():
    print("GPU :", torch.cuda.get_device_name(0))
elif COLAB:
    raise RuntimeError("pas de GPU : Exécution → Modifier le type d'exécution → GPU (T4)")
else:
    print("pas de GPU : tout tournera sur CPU (lent)")
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
    extras: str = "vision"  # pyproject extras installed on Colab

    def build(self) -> dict:
        cells = [
            header(self.name, self.title, self.intro, self.gpu),
            md("## Paramètres"),
            code(self.params, tags=["parameters"]),
            md("## Environnement"),
            code(SETUP.replace("[vision]", f"[{self.extras}]")),
            *([code(GPU_CHECK)] if self.gpu else []),
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
    remplacement de fond (docs/03-classifieur.md §3). Pas de GPU nécessaire. Statistiques
    détaillées (déséquilibre, couverture, splits, photométrie, doublons) :
    `06_stats_classifieur` (docs/19).
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

        import torch

        from vision.datasets.augment import build_transform
        from vision.datasets.batch_augment import BatchAugment
        from vision.eval.gradcam import denormalize

        random.seed(SEED)
        torch.manual_seed(SEED)
        r = df[df["source"] == "plantvillage"].sample(1, random_state=SEED).iloc[0]
        img = read_rgb(DATA_DIR / r["path"])
        # Étage CPU (workers : géométrie, ombres, CLAHE) puis étage par batch (GPU à
        # l'entraînement, CPU ici : couleur, LED, flou, bruit, JPEG, occlusions).
        strong = build_transform("strong", 224)
        x = torch.stack([strong(image=img)["image"] for _ in range(N_EXAMPLES)])
        x = BatchAugment("strong")(x)
        fig, axes = plt.subplots(1, N_EXAMPLES + 1, figsize=(2.2 * (N_EXAMPLES + 1), 2.4))
        axes[0].imshow(img)
        axes[0].set_title("original", fontsize=8)
        for ax, aug in zip(axes[1:], denormalize(x)):
            ax.imshow(aug)
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


# ------------------------------------------------------------------------- 05 détection

NB_DETECTION = Notebook(
    name="05_detection.ipynb",
    title="05 — Détection YOLO et deux étages",
    intro="""
    Phase 2 (docs/04-detection-yolo.md) : jeu YOLO `data/yolo/` (PlantDoc + PlantVillage,
    classe `feuille`), entraînement du détecteur suivi dans MLflow, puis pipeline deux étages
    (YOLO → crops → classifieur de la phase 1) évalué de bout en bout sur PlantDoc TEST.
    `YOLO_RUN` renseigné : pas d'entraînement, le run existant est évalué.
    """,
    params="""
    CONFIG = "configs/yolo_v8n.yaml"
    SET = []  # surcharges, ex. ["yolo.epochs=50", "model=yolov8s.pt"]
    DEVICE = None  # None : Ultralytics choisit (GPU 0 s'il y en a un)
    YOLO_RUN = None  # run existant (runs/<id>/best.pt) : saute l'entraînement
    PV_PER_CLASS = 40  # feuilles PlantVillage par classe dans le jeu YOLO
    REBUILD = False  # reconstruit data/yolo/ même s'il existe
    CLF_RUN = None  # classifieur de la phase 1 pour les deux étages ; None : le plus récent
    LIMIT = 0  # images PlantDoc TEST évaluées (0 : toutes)
    DATASETS = ["index", "plantvillage", "plantdoc"]
    """,
    gpu=True,
    extras="vision,detection",
    body=[
        md("## Jeu YOLO `data/yolo/`"),
        code("""
        from IPython.display import Image, display

        from vision.datasets.build_index import DATA_DIR
        from vision.labeling import build_yolo_dataset as byd

        YOLO_DIR = DATA_DIR / byd.OUT_NAME
        if REBUILD or not (YOLO_DIR / byd.MANIFEST).exists():
            byd.build(DATA_DIR, YOLO_DIR, PV_PER_CLASS, os.cpu_count())
        """),
        code("""
        import pandas as pd

        manifest = pd.read_parquet(YOLO_DIR / byd.MANIFEST)
        byd.report(manifest)
        byd.preview(YOLO_DIR, "train", path=YOLO_DIR / "preview_train.png")
        display(Image(filename=YOLO_DIR / "preview_train.png"))
        """),
        md("## Configuration"),
        code("""
        import yaml

        from vision.train.config import apply_overrides, load_config

        # Colab : tous les cœurs pour le chargement, base MLflow séparée de celle du PC.
        YOLO_ENV_SET = (
            [f"yolo.workers={os.cpu_count()}", f"mlflow.tracking_uri={drive_data.COLAB_MLFLOW}"]
            if COLAB
            else []
        )
        cfg = apply_overrides(load_config(ROOT / CONFIG), YOLO_ENV_SET + SET)
        print(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
        """),
        md("## Entraînement"),
        code("""
        from vision.train.train_yolo import run

        if YOLO_RUN is None:
            with drive_data.PeriodicSync(drive_data.OUTPUTS, DRIVE_DIR):
                YOLO_RUN = run(cfg, DEVICE).name
        print("YOLO_RUN =", YOLO_RUN)
        """),
        md("## Courbes et métriques (val, puis test)"),
        code("""
        UL = ROOT / "runs" / "ultralytics"
        for png in ["results.png", "BoxPR_curve.png"]:
            for d in [UL / YOLO_RUN, UL / f"{YOLO_RUN}_test"]:
                if (d / png).exists():
                    print(d.name, png)
                    display(Image(filename=d / png))
        """),
        md("## Deux étages sur PlantDoc TEST"),
        code("""
        import json

        from vision.eval.two_stage import (
            CropClassifier,
            TwoStagePipeline,
            YoloDetector,
            evaluate,
            plantdoc_scenes,
            plot_examples,
        )
        from vision.eval.cross_domain_eval import REPORTS_DIR
        from vision.train.train_classifier import pick_device

        if CLF_RUN is None:  # the YOLO runs have a runs/ultralytics/<id>/ folder
            ckpts = [p for p in (ROOT / "runs").glob("*/best.pt") if not (UL / p.parent.name).exists()]
            if not ckpts:
                raise FileNotFoundError("aucun classifieur runs/*/best.pt : notebook 02")
            CLF_RUN = max(ckpts, key=lambda p: p.stat().st_mtime).parent.name
        print("CLF_RUN =", CLF_RUN)

        device = pick_device(DEVICE)
        pipeline = TwoStagePipeline(
            YoloDetector(ROOT / "runs" / YOLO_RUN / "best.pt", device=str(device)),
            CropClassifier(ROOT / "runs" / CLF_RUN / "best.pt", device),
        )
        scenes = plantdoc_scenes(DATA_DIR, "test")
        scenes = scenes[:LIMIT] if LIMIT else scenes
        metrics, results = evaluate(pipeline, scenes)
        OUT = REPORTS_DIR / CLF_RUN
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "two_stage_test.json").write_text(json.dumps(metrics, indent=1))
        plot_examples(scenes, results, OUT / "two_stage_test.png")
        drive_data.sync_all(DRIVE_DIR)
        display(pd.Series(metrics).to_frame("valeur"))
        display(Image(filename=OUT / "two_stage_test.png"))
        """),
        md("""
        ## Résumé

        Détecteur : `runs/<YOLO_RUN>/best.pt` (courbes dans `runs/ultralytics/<YOLO_RUN>/`) ;
        deux étages : `reports/<CLF_RUN>/two_stage_test.{json,png}`. Critère de la feuille de
        route (docs/07) : mAP@0.5 « feuille » ≥ 0,6. Suite : pseudo-labels SAM 2 et Label
        Studio (`python -m vision.labeling.pseudo_labels`, docs/04 §2).
        """),
    ],
)

# ----------------------------------------------------------- 06 statistiques classifieur

NB_STATS_CLF = Notebook(
    name="06_stats_classifieur.ipynb",
    title="06 — Statistiques du jeu du classifieur",
    intro="""
    Vue statistique de `data/index.parquet` (docs/19 §3) : effectifs et déséquilibre,
    couverture de la taxonomie par source, cohérence des splits, géométrie, photométrie et
    écart de domaine PlantVillage / CCMT vs PlantDoc, quasi-doublons et bruit d'étiquetage,
    embeddings (optionnel). Le calcul est dans `vision/datasets/stats.py` ; les chiffres clés
    et les figures vont dans `reports/datasets/classifieur/`. CPU seulement.
    """,
    params="""
    N_SAMPLE = 4000  # images de l'échantillon photométrique (stratifié source × classe)
    MIN_VAL_TEST = 20  # alerte : classes sous ce seuil en val ou en test
    CLF_RUN = None  # classifieur des embeddings (runs/<CLF_RUN>/best.pt) ; None : sautés
    SEED = 0
    DATASETS = ["index", "plantvillage", "ccmt", "plantdoc"]
    """,
    extras="vision,stats",
    body=[
        md("## Index"),
        code("""
        import pandas as pd
        from IPython.display import Markdown, display

        from common.report import REPORTS_DIR, file_sha256, write_report
        from vision.datasets import stats as st
        from vision.datasets import stats_plots as sp
        from vision.datasets.build_index import (
            DATA_DIR, INDEX_NAME, REJECTS_NAME, low_eval_classes, read_index_meta,
        )
        from vision.datasets.dataset import load_index

        OUT = REPORTS_DIR / "classifieur"
        OUT.mkdir(parents=True, exist_ok=True)
        raw = pd.read_parquet(DATA_DIR / INDEX_NAME)  # avec les groupes contradictoires
        df = load_index(DATA_DIR / INDEX_NAME)  # ce que voit l'entraînement
        meta = read_index_meta(DATA_DIR / INDEX_NAME)
        SUMMARY = {
            "taxonomy_version": meta["taxonomy_version"],
            "index_sha256": file_sha256(DATA_DIR / INDEX_NAME),
            "n_images_index": len(raw),
            "n_images": len(df),
            "ecartees_contradictoires": len(raw) - len(df),
            "n_especes": df["espece"].nunique(),
            "n_classes": df["classe"].nunique(),
        }
        SECTIONS = {}
        display(pd.Series(SUMMARY).to_frame("valeur"))
        """),
        md("""
        ## 3.1 Effectifs et déséquilibre

        Tables après retrait des groupes contradictoires (ce que voit l'entraînement), puis
        source × split avant retrait. Indicateurs sur train : ratio max/min, entropie
        normalisée (1 : uniforme), Gini (0 : uniforme), nombre effectif de classes.
        """),
        code("""
        for rows in ["source", "espece", "classe"]:
            print(f"{rows} × split")
            display(st.counts(df, rows))
        print("source × split avant retrait des groupes contradictoires")
        display(st.counts(raw, "source"))
        SECTIONS["Source × split"] = st.counts(df, "source")
        """),
        code("""
        levels = st.imbalance_by_level(df)
        display(levels)
        tail = st.long_tail(df)
        display(sp.plot_long_tail(tail, OUT / "longue_traine.png"))
        low = low_eval_classes(df, MIN_VAL_TEST)
        print(f"classes sous {MIN_VAL_TEST} images en val ou en test : {len(low)}")
        display(pd.Series(low, name="effectifs", dtype=str).to_frame())
        SUMMARY.update(desequilibre_train=levels.to_dict(orient="index"), classes_sous_min=low)
        SECTIONS["Déséquilibre (train)"] = levels
        """),
        md("""
        ## 3.2 Couverture de la taxonomie

        Les classes **mono-source** sont celles où le modèle peut apprendre la source (fond
        uni PlantVillage…) plutôt que le symptôme : à rapporter à part en cross-domain.
        """),
        code("""
        ct, share = st.coverage(df)
        display(ct)
        display(share.round(2))
        mono = st.mono_source(df)
        print(f"{len(mono)} classes mono-source sur {df['classe'].nunique()}")
        display(mono)
        amb = st.ambiguous_weight(df)
        print(f"classes ambiguës : {len(amb['classes'])}, {amb['n_images']} images "
              f"({amb['part']:.1%})", amb["par_classe"])
        masks = st.mask_share(df)
        display(masks.to_frame())
        SUMMARY.update(classes_mono_source=mono["source"].to_dict(), ambigues=amb,
                       part_masque=masks.to_dict())
        SECTIONS["Classes mono-source"] = mono
        """),
        md("""
        ## 3.3 Cohérence des splits

        Divergence de Jensen-Shannon (bits, 0 : distributions identiques) entre les
        distributions de classes, χ² classe × split par source (p élevée attendue : splits
        stratifiés), fuite de groupes (doit afficher 0), classes de `test_xdomain` absentes
        du train.
        """),
        code("""
        div = st.split_divergence(df)
        display(pd.Series(div["js"], name="JS (bits)").to_frame())
        display(pd.DataFrame(div["chi2"]).T)
        leaks = st.group_leaks(df)
        print(f"groupes dans plusieurs splits : {len(leaks)} (attendu : 0)")
        gaps = st.xdomain_gaps(df)
        print("test_xdomain sans train :", gaps["xdomain_sans_train"])
        print("train sans test_xdomain :", len(gaps["train_sans_xdomain"]), "classes")
        SUMMARY.update(js_splits=div["js"], chi2_par_source=div["chi2"],
                       fuites_groupes=len(leaks), xdomain=gaps)
        """),
        md("""
        ## 3.4 Géométrie

        Part des images dont le petit côté est sous la résolution d'entrée (agrandies au
        redimensionnement).
        """),
        code("""
        geo = st.geometry(df, st.INPUT_SIZE)
        display(geo)
        display(sp.plot_distributions(df.assign(aspect=df["width"] / df["height"]),
                                      ["width", "height", "aspect"], log=(),
                                      path=OUT / "geometrie.png"))
        SUMMARY["part_petites_images"] = geo[("petite", f"part<{st.INPUT_SIZE}")].to_dict()
        """),
        md("""
        ## 3.5 Photométrie et écart de domaine

        Sur `N_SAMPLE` images : luminosité, contraste, saturation, teinte dominante, netteté
        (variance du laplacien), part de fond uni (bordure proche de sa médiane). L'écart
        PlantDoc vs PV + CCMT explique la chute cross-domain (docs/14) ; `hors_plage_ref` est
        la part de PlantDoc hors du [p1, p99] du domaine d'entraînement.
        """),
        code("""
        photo = st.photometry_table(df, DATA_DIR, N_SAMPLE, SEED)
        photo.to_csv(OUT / "photometrie.csv", index=False)
        display(sp.plot_distributions(photo, list(st.DESCRIPTORS), path=OUT / "photometrie.png"))
        display(sp.plot_pca(st.descriptor_pca(photo), path=OUT / "photometrie_pca.png"))
        gap = st.domain_gap(photo)
        display(gap)
        SUMMARY["ecart_domaine"] = gap.to_dict(orient="index")
        SECTIONS["Écart de domaine (PlantDoc vs PV + CCMT)"] = gap
        """),
        code("""
        # Mêmes descripteurs après les augmentations fortes (docs/03 §3, sans remplacement de
        # fond) : couvrent-elles la plage de PlantDoc ? hors_plage_ref : PlantDoc hors du batch.
        import torch

        from vision.datasets.augment import build_transform
        from vision.datasets.batch_augment import BatchAugment
        from vision.datasets.dataset import read_rgb
        from vision.eval.gradcam import denormalize

        torch.manual_seed(SEED)
        labo = st.stratified_sample(df[df["source"].isin(["plantvillage", "ccmt"])], 256, SEED)
        strong = build_transform("strong", st.INPUT_SIZE)
        x = torch.stack([strong(image=read_rgb(DATA_DIR / p))["image"] for p in labo["path"]])
        aug = st.photometry_images(denormalize(BatchAugment("strong")(x)), source="augmenté")
        both = pd.concat([photo, aug], ignore_index=True)
        display(sp.plot_distributions(both, list(st.DESCRIPTORS),
                                      path=OUT / "photometrie_augmente.png"))
        gap_aug = st.domain_gap(both, ref=["augmenté"])
        display(gap_aug)
        SUMMARY["ecart_plantdoc_vs_augmente"] = gap_aug.to_dict(orient="index")
        """),
        md("""
        ## 3.6 Quasi-doublons et bruit d'étiquetage

        Paires candidates (pHash ≤ 6) et leur distance dHash : la bimodalité justifie le seuil
        de confirmation dHash ≤ 8 (docs/02 §3). Puis les groupes contradictoires (même image
        dans plusieurs classes) et les fichiers rejetés.
        """),
        code("""
        gs = st.group_sizes(raw)
        print(f"{gs['n_groupes_doublons']} groupes de quasi-doublons, {gs['images_en_doublon']} "
              f"images, plus gros groupe : {gs['max']} (attendu : 21)")
        display(pd.Series(gs["distribution"], name="groupes").rename_axis("taille").to_frame().T)
        pairs = st.candidate_pair_distances(raw["phash"].to_numpy(), raw["dhash"].to_numpy(),
                                            meta["max_hamming"])
        confirmed = (pairs["d_dhash"] <= meta["max_hamming_confirm"]).sum()
        print(f"{len(pairs)} paires candidates (pHash ≤ {meta['max_hamming']}), "
              f"{confirmed} confirmées (dHash ≤ {meta['max_hamming_confirm']})")
        display(sp.plot_hash_distances(pairs, meta["max_hamming_confirm"],
                                       OUT / "distances_hash.png"))
        SUMMARY.update(groupes=gs, paires_candidates=len(pairs), paires_confirmees=confirmed)
        """),
        code("""
        contra = st.contradictory_groups(raw)
        print(f"{contra['n_groupes']} groupes contradictoires, {contra['n_images']} images",
              contra["par_source"])
        display(contra["paires"].head(20))
        classe_of = raw.set_index("path")["classe"].astype(str)
        ex = [p for ps in contra["groupes"]["paths"].head(8) for p in ps[:3]]
        if ex:
            display(sp.plot_image_grid([DATA_DIR / p for p in ex],
                                       [classe_of[p].split("/", 1)[1] for p in ex],
                                       path=OUT / "contradictoires.png"))
        rejects = st.read_rejects(DATA_DIR / REJECTS_NAME)
        print(f"{len(rejects)} fichiers rejetés")
        display(rejects.groupby(["source", "dossier"]).size().rename("n").to_frame())
        SUMMARY.update(contradictoires={k: contra[k] for k in ["n_groupes", "n_images",
                                                               "par_source"]},
                       rejets=rejects["source"].value_counts().to_dict())
        SECTIONS["Paires de classes des groupes contradictoires"] = contra["paires"].head(20)
        """),
        md("""
        ## 3.7 Embeddings (optionnel)

        Features du classifieur `CLF_RUN` sur un échantillon, projetées en 2D (UMAP, sinon
        t-SNE). Une séparation nette par source au sein d'une même espèce signale un
        raccourci de domaine. Seule cellule qui profite d'un GPU.
        """),
        code("""
        if CLF_RUN is None:
            print("CLF_RUN = None : embeddings sautés")
        else:
            from vision.train.train_classifier import pick_device

            emb = st.stratified_sample(df, min(N_SAMPLE, 2000), SEED)
            feats = st.extract_features(ROOT / "runs" / CLF_RUN / "best.pt", emb["path"].tolist(),
                                        DATA_DIR, str(pick_device(None)))
            xy, method = st.embed_2d(feats, seed=SEED)
            display(sp.plot_embedding(xy, emb["source"], f"{method} : source",
                                      OUT / "embeddings_source.png"))
            display(sp.plot_embedding(xy, emb["espece"], f"{method} : espèce",
                                      OUT / "embeddings_espece.png"))
        """),
        md("## Rapport"),
        code("""
        write_report(OUT, SUMMARY, SECTIONS)
        drive_data.sync_all(DRIVE_DIR)
        display(Markdown((OUT / "summary.md").read_text(encoding="utf-8")))
        """),
        md("""
        ## Résumé

        `reports/datasets/classifieur/` : `summary.json` (chiffres clés, version de la
        taxonomie, hash de l'index), `summary.md`, `photometrie.csv` et les figures. À recouper
        avec docs/02 : PlantVillage train 43 434, CCMT train 20 111, crops PlantDoc 8 704, plus
        gros groupe 21, `pomme_de_terre/sain` à 15 en val et en test. Décisions (docs/19 §9) :
        classes mono-source à suivre en cross-domain, augmentations au vu de l'écart de
        domaine, nettoyage des groupes contradictoires CCMT.
        """),
    ],
)

# ------------------------------------------------------------------ 07 statistiques YOLO

NB_STATS_YOLO = Notebook(
    name="07_stats_yolo.ipynb",
    title="07 — Statistiques du jeu de détection",
    intro="""
    Vue statistique de `data/yolo/` (docs/19 §4) : effectifs par split, source et classe,
    géométrie des boîtes (petits objets, cadrage), qualité des annotations (doublons, boîtes
    imbriquées, dégénérées), fuite de groupes, planches d'exemples. Calcul dans
    `vision/datasets/stats.py` ; sorties dans `reports/datasets/yolo/`. CPU seulement.
    """,
    params="""
    IMG_SIZE = 640  # entrée du détecteur (letterbox : grand côté -> IMG_SIZE)
    N_EXAMPLES = 8  # images par planche
    SEED = 0
    SOURCE = None  # planches : "plantdoc" ou "plantvillage" ; None : toutes
    PV_PER_CLASS = 40  # si data/yolo/ doit être reconstruit (docs/04 §2)
    DATASETS = ["index"]  # data/yolo/ : jeu `yolo` du Drive, sinon reconstruit ci-dessous
    """,
    body=[
        md("## Jeu `data/yolo/`"),
        code("""
        import pandas as pd
        import yaml
        from IPython.display import Markdown, display

        from common.report import REPORTS_DIR, write_report
        from vision.datasets import stats as st
        from vision.datasets import stats_plots as sp
        from vision.datasets.build_index import DATA_DIR, INDEX_NAME
        from vision.labeling import build_yolo_dataset as byd

        YOLO_DIR = DATA_DIR / byd.OUT_NAME
        try:
            drive_data.ensure(["yolo"], DRIVE_DIR if COLAB else None)
        except RuntimeError as e:
            print(e, "\\n-> reconstruction depuis PlantVillage et PlantDoc")
            drive_data.ensure(["plantvillage", "plantdoc"], DRIVE_DIR if COLAB else None)
            byd.build(DATA_DIR, YOLO_DIR, PV_PER_CLASS, os.cpu_count())

        OUT = REPORTS_DIR / "yolo"
        OUT.mkdir(parents=True, exist_ok=True)
        manifest = pd.read_parquet(YOLO_DIR / byd.MANIFEST)
        names = yaml.safe_load((YOLO_DIR / "data.yaml").read_text())["names"]
        NAMES = [names[i] for i in sorted(names)]
        boxes = st.read_yolo_labels(YOLO_DIR, manifest)
        counts = st.yolo_counts(manifest, boxes, NAMES)
        SUMMARY = {"n_images": counts["n_images"], "n_boites": counts["n_boites"],
                   "classes": NAMES, "classes_sans_annotation": counts["classes_sans_annotation"],
                   "images_sans_boite": len(counts["images_sans_boite"])}
        SECTIONS = {}
        """),
        code("""
        # À lire avant toute métrique par classe du détecteur.
        empty = counts["classes_sans_annotation"]
        if empty:
            display(Markdown(
                f"> ⚠️ **{len(empty)} classe(s) sans aucune annotation : {', '.join(empty)}.** "
                f"Elles sont déclarées dans `data.yaml`, mais seules les métriques de "
                f"{', '.join(n for n in NAMES if n not in empty)} ont un sens. "
                f"{SUMMARY['images_sans_boite']} image(s) sans boîte."
            ))
        display(pd.Series(SUMMARY).to_frame("valeur"))
        """),
        md("## 4.1 Effectifs"),
        code("""
        print("images source × split")
        display(counts["images"])
        print("boîtes source × split")
        display(counts["boites"])
        display(counts["boites_par_classe"])
        print(f"{len(counts['images_sans_boite'])} images sans boîte (négatifs)")
        display(counts["images_sans_boite"].head(20))
        neg = counts["images_sans_boite"].head(N_EXAMPLES)
        if len(neg):
            display(sp.plot_image_grid([YOLO_DIR / p for p in neg["image"]], list(neg["source"]),
                                       cols=4, path=OUT / "sans_boite.png"))
        bad = st.nboxes_consistency(manifest, boxes)
        print(f"n_boxes du manifest ≠ lignes de labels/ : {len(bad)} images (attendu : 0)")
        display(bad.head(20))
        SUMMARY["incoherences_n_boxes"] = len(bad)
        SECTIONS["Images source × split"] = counts["images"]
        SECTIONS["Boîtes source × split"] = counts["boites"]
        """),
        md("""
        ## 4.2 Géométrie des boîtes

        Tailles à l'entrée du réseau (`IMG_SIZE`) : catégories COCO small (< 32²), medium
        (< 96²), large. La mAP chute sur les petits objets : leur part guide le choix de la
        taille d'entrée (640 vs 960) ou du tuilage.
        """),
        code("""
        geom = st.box_geometry(boxes, IMG_SIZE)
        per_img = st.boxes_per_image(manifest, boxes)
        display(per_img.groupby("source")["n_lignes"].describe())
        display(geom.groupby("source")[["aire_rel", "w_px", "h_px", "aspect"]].median())
        coco = st.coco_share(geom)
        display(coco)
        display(sp.plot_box_geometry(geom, OUT / "geometrie_boites.png"))
        maps = {s: st.center_heatmap(g) for s, g in geom.groupby("source")}
        display(sp.plot_heatmaps(maps, OUT / "centres.png"))
        SUMMARY.update(part_coco=coco.to_dict(orient="index"),
                       boites_par_image=per_img.groupby("source")["n_lignes"].mean().to_dict())
        SECTIONS["Catégories COCO à IMG_SIZE"] = coco
        """),
        md("""
        ## 4.3 Qualité des annotations

        Doublons probables (IoU > 0,9), boîtes imbriquées, boîtes dégénérées (< 2 px à
        `IMG_SIZE`) ou débordant de l'image ; fuite de groupes entre splits. Le manifest n'a
        pas de `groupe` pour PlantVillage : il est repris de `index.parquet` par `path`.
        """),
        code("""
        q = st.box_quality(boxes, IMG_SIZE)
        display(pd.Series({k: len(v) for k, v in q.items()}, name="n").to_frame())
        for k in ["doublons", "imbriquees"]:
            if len(q[k]):
                print(k)
                display(q[k].head(10))
        index = pd.read_parquet(DATA_DIR / INDEX_NAME, columns=["path", "groupe"])
        leaks = st.yolo_group_leaks(manifest, index)
        print(f"groupes dans plusieurs splits : {leaks['n_fuites']} (attendu : 0) ; "
              f"images non contrôlées : {leaks['non_controlees']}",
              leaks["non_controlees_par_source"])
        display(leaks["fuites"].head(10))
        SUMMARY.update(qualite={k: len(v) for k, v in q.items()},
                       fuites_groupes=leaks["n_fuites"], non_controlees=leaks["non_controlees"])
        """),
        md("## 4.4 Exemples"),
        code("""
        sel = manifest if SOURCE is None else manifest[manifest["source"] == SOURCE]
        for split in ["train", "val", "test"]:
            sub = sel[sel["split"] == split]
            if len(sub):
                print(split)
                display(sp.plot_yolo_examples(YOLO_DIR, sub, boxes, N_EXAMPLES, SEED,
                                              OUT / f"exemples_{split}.png"))
        """),
        md("## Rapport"),
        code("""
        write_report(OUT, SUMMARY, SECTIONS)
        drive_data.sync_all(DRIVE_DIR)
        display(Markdown((OUT / "summary.md").read_text(encoding="utf-8")))
        """),
        md("""
        ## Résumé

        `reports/datasets/yolo/` : `summary.json`, `summary.md`, figures. Attendu (docs/19
        §4) : 4 427 images, 10 743 boîtes, toutes `feuille`. Décisions (docs/19 §9) : retirer
        `plante` et `fruit` de `data.yaml` ou lancer leur annotation ; taille d'entrée selon la
        part de petites boîtes.
        """),
    ],
)

# -------------------------------------------------------------- 08 statistiques capteurs

NB_STATS_CAPTEURS = Notebook(
    name="08_stats_capteurs.ipynb",
    title="08 — Statistiques des capteurs et actionneurs",
    intro="""
    Séries temporelles de la serre (docs/19 §5) : couverture et trous, qualité,
    distributions et valeurs aberrantes, profils journaliers, DLI, autocorrélations
    (horizon de prévision), corrélations, cycles des actionneurs et délai commande → effet,
    alertes et vision. Source : un scénario figé (`data/scenarios/<nom>/serre.db`, figé à la
    volée s'il manque), l'historique simulé de `sim.dataset.generate` ou une base SQLite.
    Calcul dans `sim/stats.py` ; sorties dans `reports/datasets/capteurs/<source>/`.
    """,
    params="""
    SOURCE = "scenario:journee"  # "scenario:<nom>", "sim" ou chemin d'une base SQLite
    SIM_DAYS = 30  # SOURCE = "sim" : jours simulés (pas de 10 min)
    SIM_SEED = 0
    GAP_FACTOR = 2  # trou : écart > GAP_FACTOR × la cadence médiane du capteur
    FUSEAU = "Europe/Paris"  # heure locale des profils ; None : celui de la table serre
    PANNES = []  # sim/faults.py, ex. ["fige:z1/temperature@30-90", "deconnexion:esp32-02@10-40"]
    DATASETS = []  # aucune archive Drive : scénarios figés à la volée, `sim` généré
    """,
    extras="vision,controle,backend",
    body=[
        md("## Données"),
        code("""
        import re

        import pandas as pd
        from IPython.display import Markdown, display

        from common.report import REPORTS_DIR, write_report
        from sim import stats as ss
        from sim import stats_plots as sp

        src = ss.load_source(SOURCE, SIM_DAYS, SIM_SEED)
        L = ss.inject_faults(src.mesures, PANNES)  # mesures en format long
        TZ = FUSEAU or src.serre.get("fuseau", "Europe/Paris")
        STEP = "10min"
        W = ss.wide(L, STEP)  # table large (zone, type), pas régulier
        OUT = REPORTS_DIR / "capteurs" / re.sub(r"[^\\w-]+", "_", SOURCE).strip("_")
        OUT.mkdir(parents=True, exist_ok=True)
        SUMMARY = {"source": SOURCE, "pannes": PANNES, "debut": L["ts"].min(),
                   "fin": L["ts"].max(), "n_mesures": len(L),
                   "n_capteurs": L["capteur_id"].nunique(), "n_etats": len(src.etats),
                   "fuseau": TZ}
        SECTIONS = {}
        display(pd.Series(SUMMARY).to_frame("valeur"))
        """),
        md("""
        ## 5.1 Couverture et qualité

        Trou : écart entre deux mesures > `GAP_FACTOR` × la cadence médiane du capteur. Les
        scénarios n'ont que des mesures `ok` : cela ne prouve pas l'absence de défaut ;
        renseigner `PANNES` pour vérifier que ces statistiques révèlent les pannes simulées.
        """),
        code("""
        cov = ss.coverage(L, GAP_FACTOR)
        display(cov)
        gaps = ss.gaps(L, GAP_FACTOR)
        display(sp.plot_timeline(L, gaps, OUT / "couverture.png"))
        share, only_ok = ss.quality_share(L)
        display(share)
        if only_ok:
            print("Toutes les mesures sont `ok` : aucun défaut signalé, ce qui ne veut pas dire "
                  "qu'il n'y en a pas (injecter des PANNES).")
        SUMMARY.update(trous=int(cov["n_trous"].sum()), trou_max_s=float(cov["trou_max_s"].max()),
                       que_des_ok=only_ok)
        SECTIONS["Couverture"] = cov
        """),
        md("""
        ## 5.2 Distributions

        Résumés par type × zone, valeurs hors bornes physiques (`ss.PHYSICAL_BOUNDS`),
        saturation du capteur de lumière, valeurs aberrantes par z-score robuste (médiane,
        MAD) sur fenêtre glissante d'une heure.
        """),
        code("""
        display(ss.summaries(L))
        display(sp.plot_histograms(L, OUT / "histogrammes.png"))
        oob = ss.out_of_bounds(L)
        print(f"{len(oob)} valeurs hors bornes physiques")
        display(oob.groupby(["zone", "type"]).size().rename("n").to_frame())
        display(ss.saturation(L))
        outl = ss.robust_outliers(L)
        print(f"{len(outl)} valeurs aberrantes (|z robuste| > 5)")
        display(outl.groupby(["zone", "type"]).size().rename("n").to_frame())
        SUMMARY.update(hors_bornes=len(oob), aberrantes=len(outl))
        SECTIONS["Résumés"] = ss.summaries(L)
        """),
        md("""
        ## 5.3 Dynamique temporelle

        Profils journaliers en heure locale (médiane et IQR), DLI (même conversion lux → PPFD
        que la serre), autocorrélations : l'horizon où l'ACF passe sous 0,5 borne ce que la
        persistance prévoit seule (niveau 2, docs/11). Décomposition tendance / journalier /
        résidu, corrélations entre capteurs d'une zone.
        """),
        code("""
        prof = ss.daily_profile(L, ["temperature", "humidite", "lux", "co2"], TZ)
        display(sp.plot_daily_profiles(prof, OUT / "profils_journaliers.png"))
        dli = ss.dli(L, src.serre.get("lux_vers_ppfd", ss.LUX_VERS_PPFD), TZ)
        display(dli)
        acfs = ss.autocorrelations(W, "24h")
        horizon = ss.useful_horizon(acfs)
        display(horizon.rename("horizon ACF < 0,5 (h)").to_frame())
        display(sp.plot_acf(acfs, path=OUT / "autocorrelations.png"))
        SUMMARY.update(dli=dli.to_dict(orient="records"),
                       horizon_h={" ".join(k): v for k, v in horizon.items()})
        SECTIONS["Horizon ACF < 0,5 (h)"] = horizon.to_frame("h")
        """),
        code("""
        for zone in sorted(W.columns.get_level_values(0).unique()):
            if (zone, "temperature") in W.columns:
                comps, parts = ss.decompose(W[(zone, "temperature")])
                print(zone, "température :", parts)
                display(sp.plot_decomposition(comps, f"{zone} température",
                                              OUT / f"decomposition_{zone}.png"))
            corr = ss.correlations(W, zone)
            display(sp.plot_corr(corr, zone, OUT / f"correlations_{zone}.png"))
        """),
        md("""
        ## 5.4 Actionneurs, alertes, vision

        Taux d'activation et durées des cycles ; délai commande → effet : décalage du pic de
        corrélation croisée entre l'état d'un actionneur et la dérivée du capteur visé
        (ventilateur → T°, brumisateur → HR, pompe → humidité du sol).
        """),
        code("""
        duty = ss.duty_cycles(src.etats)
        display(duty)
        display(sp.plot_states(src.etats, path=OUT / "actionneurs.png"))
        lag = ss.lag_effect(src.etats, L)
        display(lag)
        SUMMARY.update(taux_activation={" ".join(k): v for k, v in
                                        duty["taux_activation"].items()},
                       delai_effet=lag.to_dict(orient="records"))
        SECTIONS["Actionneurs"] = duty
        SECTIONS["Délai commande → effet"] = lag
        """),
        code("""
        al = ss.alerts_summary(src.alertes)
        print(f"{al['n']} alertes")
        if al["n"]:
            display(al["niveau_zone"])
            display(al["par_source"].to_frame())
            display(sp.plot_alerts(src.alertes, OUT / "alertes.png"))
        vi = ss.vision_summary(src.vision)
        print(f"{vi['n']} analyses vision")
        if vi["n"]:
            display(vi["par_zone"].to_frame())
            display(vi["sante"])
            display(vi["confiances"])
        SUMMARY.update(alertes=al["n"], analyses_vision=vi["n"])
        """),
        md("## Rapport"),
        code("""
        write_report(OUT, SUMMARY, SECTIONS)
        drive_data.sync_all(DRIVE_DIR)
        display(Markdown((OUT / "summary.md").read_text(encoding="utf-8")))
        """),
        md("""
        ## Résumé

        `reports/datasets/capteurs/<source>/` : `summary.json`, `summary.md`, figures.
        Décisions (docs/19 §9) : horizon de prévision du niveau 2 au vu des autocorrélations,
        seuils de trous (`capteur_muet_s`) et de valeurs aberrantes du contrôleur. Ce notebook
        passe en P1 dès que la base réelle de la serre existe (`SOURCE` = son chemin).
        """),
    ],
)

NOTEBOOKS = [
    NB_DONNEES,
    NB_ENTRAINEMENT,
    NB_EVALUATION,
    NB_ABLATIONS,
    NB_DETECTION,
    NB_STATS_CLF,
    NB_STATS_YOLO,
    NB_STATS_CAPTEURS,
]


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
