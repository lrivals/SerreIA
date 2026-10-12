# 03 — Phase 1 : classifieur spécialisé

**But** : un modèle léger, déployable sur Hailo, qui dit pour une image de feuille ou de plante **quelle espèce**, **saine ou anormale**, et **quelle maladie ou quel nuisible**, et qui reste fiable **hors des conditions de laboratoire**.

## 1. Modèle — `vision/models/multihead.py`

```
image 224×224 ──► backbone timm (sans tête) ──► features (pool) ──┬─► tête espece   (16)
                                                                  ├─► tête sante    (2)
                                                                  └─► tête classe   (~55)
```

| Backbone | Paramètres | Rôle |
|---|---|---|
| `efficientnet_b0` | 5,3 M | **choix principal**, bien supporté par Hailo |
| `mobilenetv3_large_100` | 5,5 M | alternative plus rapide |
| `convnext_nano` | 15 M | référence haute (plafond de performance, pas forcément déployé) |

Poids pré-entraînés ImageNet. Têtes : `Dropout(0.2)` + `Linear`.

**Opérateurs** : n'utiliser que des couches compatibles avec le Hailo Dataflow Compiler (conv, BN, ReLU/SiLU/HardSwish, pooling, linear). Vérifier tôt avec un export ONNX de test (voir [05](05-edge-deploiement.md)).

## 2. Entraînement — `vision/train/train_classifier.py`

| Élément | Valeur de départ |
|---|---|
| Loss | `L = 1.0·CE(classe) + 0.5·CE(espece) + 1.0·CE(sante)`, label smoothing 0,1 |
| Classes ambiguës | exclues de la loss `classe` (cible `-100`), conservées pour `espece` et `sante` ; la tête `classe` ne les prédit pas (53 sorties) |
| Étiquettes contradictoires | tout `groupe` de quasi-doublons portant plusieurs `classe` est écarté (715 images : 612 CCMT, 64 PV, 39 PlantDoc) |
| Déséquilibre | `WeightedRandomSampler` (poids ∝ 1/√effectif de la classe) |
| Optimiseur | AdamW, lr 1e-3 (têtes) / 3e-4 (backbone), weight decay 0,05 |
| Planning | 2 epochs avec backbone gelé, puis fine-tuning complet ; cosine + warmup ; 25–30 epochs |
| Batch | 64, AMP fp16 (adapté aux 6 Go de VRAM) |
| Résolution | 224 (puis essai à 256 / 288 si le gain cross-domain le justifie) |
| Sélection du modèle | meilleur **F1 macro `sante` sur `val`** + suivi du F1 `classe` |
| Seed | fixée, enregistrée |

Configuration en YAML (`configs/clf_effnet_b0.yaml`, chargée par `vision/train/config.py` : héritage `_base_`, surcharges `--set cle=valeur`). Chaque run est enregistré dans **MLflow** : config, version de la taxonomie, hash de l'index, métriques et artefacts (matrices, Grad-CAM, poids).

## 3. Écart de domaine : le cœur du travail

PlantVillage montre une feuille isolée sur fond uni, sous une lumière homogène. La serre offre au contraire un feuillage dense, un fond encombré et un éclairage LED horticole (rose/violet). Un modèle naïf atteint environ 99 % sur PlantVillage et s'effondre sur des images réelles. Trois leviers permettent de l'éviter.

### 3.1 Augmentations (`vision/datasets/augment.py`, albumentations)
- géométriques : `RandomResizedCrop(scale=0.3–1.0)`, flips, rotation ±30°, perspective ;
- photométriques : `ColorJitter` fort, **variation de teinte simulant les LED** (gain R/B), `RandomGamma`, `CLAHE` ;
- dégradations : flou de mouvement ou gaussien, bruit ISO, compression JPEG (qualité 30–90), ombres aléatoires ;
- `CoarseDropout` (occlusions par d'autres feuilles).

Les workers du DataLoader (CPU) ne font que le décodage, le remplacement de fond, la géométrie, les ombres et le CLAHE, et rendent des images uint8. Les opérations pixel par pixel (couleur, LED, gamma, flou, bruit, JPEG, `CoarseDropout`) et la normalisation tournent par batch sur le GPU (`vision/datasets/batch_augment.py`), avec des paramètres tirés pour chaque image. Le bruit ISO y est une approximation de celui d'albumentations.

### 3.2 Remplacement de fond (contribution originale) — `BackgroundPaster` dans `augment.py`
PlantVillage fournit `segmented/`, des versions détourées qui permettent d'extraire les masques.
1. Constituer `data/backgrounds/` : photos de serre, de feuillage, de terreau, de bacs hydroponiques (les nôtres, plus des images libres de droits).
2. Avec une probabilité p = 0,5, coller la feuille masquée sur un fond aléatoire (léger flou des bords, harmonisation des couleurs).
3. Variante « multi-feuilles » : coller 2 à 4 feuilles ; seule la feuille principale porte l'étiquette.

C'est l'ablation la plus importante à mesurer (avec et sans), voir §4.

Implémentation : masque = seuil sur le fond noir de `segmented/` + ouverture/fermeture + plus grande composante, trous remplis (les lésions sombres restent « feuille »). L'harmonisation ne touche que la luminance (L de LAB) : la chrominance porte les symptômes (jaunissement, taches). **`data/backgrounds/` est encore vide** : l'entraînement s'arrête avec un message explicite tant qu'il n'est pas rempli (ou mettre `augment.background.enabled=false`).

### 3.3 Grad-CAM comme garde-fou
Si les cartes d'attention tombent sur le fond ou les bords, le modèle exploite un raccourci : il faut renforcer le remplacement de fond.

## 4. Évaluation — `vision/eval/cross_domain_eval.py` (métriques : `vision/eval/metrics.py`)

| Jeu | Rôle |
|---|---|
| `test` (PV + CCMT) | performance in-domain |
| `test_xdomain` (PlantDoc, crops des bounding boxes) | **métrique de référence** : généralisation au réel |

Métriques rapportées :
- `sante` : **rappel « anormal »** (on ne veut pas rater une plante malade), précision, F1, AUROC ;
- `espece` : accuracy, F1 macro ;
- `classe` : F1 macro, top-3 accuracy, sur les classes communes à PlantDoc ;
- matrices de confusion **par source** ;
- calibration (ECE) : les seuils d'alerte de la phase 3 s'appuient sur les confiances.

### Ablations prévues
| # | Variante | Question |
|---|---|---|
| A | baseline, augmentations légères | référence |
| B | + augmentations fortes | gain photométrique |
| C | + remplacement de fond | **gain cross-domain attendu le plus fort** |
| D | B/C + CCMT en plus de PV | apport des images « terrain » de CCMT |
| E | ConvNeXt-Nano | plafond de performance |

Configurations : `configs/ablations/{A_baseline,B_strong_aug,C_background,D_ccmt,E_convnext}.yaml` (chacune hérite de la précédente ; D = configuration principale).

Sorties de l'évaluation : `reports/<run_id>/metrics.json`, `summary.md` (tableau prêt à coller), matrices de confusion `sante` et `classe` par jeu et par source. Les classes ambiguës sont rapportées à part (`sante`, `espece`). Sur `test_xdomain`, la métrique `classe` ne porte que sur les classes communes à PlantDoc et aux sources d'entraînement du run.

Livrable : `reports/phase1.md`, avec le tableau des ablations, les matrices et une planche Grad-CAM.

## 5. Explicabilité — `vision/eval/gradcam.py`
- Grad-CAM sur la dernière couche convolutive **spatiale** (détectée automatiquement : le `conv_head` de MobileNetV3, appliqué après le pooling, est ignoré), pour chaque tête ;
- planche de 32 exemples par source (bonnes et mauvaises prédictions) ;
- `--save-cams` enregistre les cartes brutes (`.npz`), réutilisées comme **pré-annotations** pour YOLO (voir [04](04-detection-yolo.md#2-annotation-semi-automatique)).

## 6. Critères de sortie de la phase 1
- F1 `sante` in-domain ≥ 0,97 ;
- **rappel « anormal » sur PlantDoc ≥ 0,80** (objectif réaliste ; la littérature rapporte de fortes chutes cross-domain) ;
- export ONNX validé (écart < 0,5 point par rapport à PyTorch) : `vision/export/to_onnx.py`.

## 7. Commandes et notebooks

Les entraînements réels se font sur GPU, via les notebooks de `notebooks/` (Colab : badge en tête de chaque notebook ; données servies par Google Drive, voir [data-drive](data-drive.md)) :

| Notebook | Rôle |
|---|---|
| `01_donnees.ipynb` | effectifs, exemples, aperçu des augmentations et du remplacement de fond |
| `02_entrainement.ipynb` | un run (`CONFIG`, `SET`) : entraînement, évaluation, Grad-CAM, ONNX |
| `03_evaluation.ipynb` | évaluation d'un run existant (`RUN_ID`, défaut : le plus récent) |
| `04_ablations.ipynb` | A–E à la suite, reprise via `reports/ablations.json`, puis `reports/phase1.md` |

Les notebooks sont générés par `tools/notebooks/build.py` (`make notebooks`, vérifié par `tests/test_notebooks.py`) : modifier le générateur, pas les `.ipynb`. Sur Colab, les sorties (`runs/`, `reports/`, `mlruns/colab/`) sont copiées sur le Drive toutes les 10 min ; sur le PC, `make harvest`.

En ligne de commande :
```bash
python -m vision.train.train_classifier --config configs/clf_effnet_b0.yaml
python -m vision.train.train_classifier --config configs/ablations/A_baseline.yaml
python -m vision.eval.cross_domain_eval --run <run_id>      # reports/<run_id>/
python -m vision.eval.gradcam --run <run_id> [--save-cams]
python -m vision.export.to_onnx --run <run_id>              # runs/<run_id>/model.onnx
python -m vision.eval.ablation_report                       # reports/ablations.json → reports/phase1.md
# smoke test CPU : --subset 512 --limit-batches 5 --device cpu --set train.epochs=2
```
Chaque run écrit `runs/<run_id>/{best,last}.pt` (poids, config, vocabulaires des têtes, version de taxonomie) et enregistre dans MLflow (SQLite `mlruns/mlflow.db`, le stockage fichier étant refusé par MLflow 3) la config aplatie, la version de la taxonomie, le sha256 de `index.parquet` et le commit git.
