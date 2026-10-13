# 04 — Phase 2 : détection YOLO et anomalies de croissance

Le classifieur répond à la question « cette image est-elle malade ? ». Dans la serre, une caméra voit **plusieurs plantes et des dizaines de feuilles** : il faut **localiser**. Il faut aussi détecter ce qu'aucun dataset ne contient (carences, stress hydrique, croissance anormale).

## 1. Architecture deux étages (recommandée)

```
image caméra ──► YOLO (détecteur générique) ──► boîtes « feuille » / « plante » / « fruit »
                                                    │ crop
                                                    ▼
                                         classifieur phase 1 ──► espece / sante / classe
```

Pourquoi ce choix plutôt qu'un YOLO à 56 classes :
- le détecteur n'a besoin que de **3 classes génériques** : annotation plus rapide et données plus abondantes ;
- le classifieur de la phase 1 est réutilisé tel quel et ré-entraînable séparément ;
- une nouvelle maladie se gère côté classifieur, sans ré-annoter de boîtes.

Une variante **YOLO un étage** (classes `sain` / `symptome` / `nuisible` directement sur les lésions) sera comparée une fois l'annotation suffisante.

**Modèle** : `YOLOv8n` ou `YOLOv8s` (les mieux supportés par le Hailo Model Zoo) ; `YOLO11n` en alternative. Entrée 640×640.
⚠️ Ultralytics est sous licence **AGPL-3.0** : sans conséquence pour un usage personnel, mais à prendre en compte en cas de diffusion ou de commercialisation.

## 2. Annotation semi-automatique — `vision/labeling/`

| Source | Ce qu'on obtient |
|---|---|
| **PlantDoc** | boîtes déjà fournies (VOC) → conversion vers le format YOLO, classes regroupées en `feuille` |
| PlantVillage `segmented/` | masque → boîte englobante automatique (1 feuille par image) |
| CCMT | Grad-CAM + **SAM 2** → boîtes candidates |
| Images de la serre | YOLO v0 + SAM 2 → pré-annotations |

Pipeline `pseudo_labels.py` :
1. Grad-CAM (phase 1) → points de forte activation ;
2. SAM 2, guidé par ces points → masque → boîte ;
3. filtres (surface minimale, confiance) ;
4. export au format **Label Studio** (JSON de pré-annotations) ;
5. **correction humaine** dans Label Studio, puis export YOLO (`images/`, `labels/*.txt`, `data.yaml`).

Objectif : environ 1 500 images corrigées pour un premier détecteur exploitable, puis croissance via l'apprentissage actif.

### Implémentation

| Module | Rôle |
|---|---|
| `yolo_format.py` | format YOLO (`labels/*.txt`, `data.yaml` sans `path`, résolu à côté du fichier), `mask_to_box`, IoU, NMS |
| `build_yolo_dataset.py` | jeu `data/yolo/` à partir de PlantDoc et de PlantVillage `segmented/` |
| `label_studio.py` | tâches de pré-annotation (JSON, sans SDK) et export Label Studio → YOLO |
| `pseudo_labels.py` | Grad-CAM (`gradcam --save-cams`) ou YOLO v0 → SAM 2 → boîtes filtrées → tâches Label Studio |

```bash
python -m vision.labeling.build_yolo_dataset --preview          # ~1 min ; planches data/yolo/preview_*.png
python -m vision.eval.gradcam --run <clf_run> --save-cams
python -m vision.labeling.pseudo_labels cams reports/<clf_run>/cams_test_ccmt_sante.npz --out labeling/ccmt.json
python -m vision.labeling.pseudo_labels detector --detector runs/<yolo_run>/best.pt --images data/serre/a_annoter --out labeling/serre.json
```

Jeu `data/yolo/` (12/10/2026, `--pv-per-class 40`) :

| Source | train | val | test | boîtes |
|---|---|---|---|---|
| PlantDoc | 2 105 | 235 | 237 | 8 893 |
| PlantVillage | 1 480 | 185 | 185 | 1 850 |

- PlantDoc : tous les labels → `feuille` ; TEST d'origine → `test` ; TRAIN → train/val **groupés** (pHash + dHash, mêmes seuils que l'index), 15 images TRAIN quasi-doublons de TEST écartées ; boîtes < 4 px ignorées.
- PlantVillage : boîte tirée du masque, échantillon par classe, **split repris de `index.parquet`**.
- Images en liens symboliques relatifs vers `data/` ; 37 images sont recopiées sans lien : celles qui ont une rotation EXIF (les boîtes VOC sont mesurées sur les pixels bruts) et les JPEG tronqués (sinon Ultralytics les réécrirait à la place du lien).
- Label Studio : définir `LOCAL_FILES_DOCUMENT_ROOT` sur `data/` (URL `/data/local-files/?d=…`) ; interface `RectangleLabels` `feuille` / `plante` / `fruit` (docstring de `label_studio.py`).

## 3. Entraînement — `vision/train/train_yolo.py`
- base : poids COCO ; augmentations Ultralytics (mosaic, HSV) + teinte LED ;
- splits **groupés** (même logique qu'en [02](02-donnees.md#3-index--visiondatasetsbuild_indexpy)) ;
- métriques : mAP@0.5, mAP@0.5:0.95, rappel par classe ;
- évaluation finale de bout en bout : **détection + classification** sur des images de la serre annotées (rappel « plante anormale » par image).

```bash
python -m vision.train.train_yolo --config configs/yolo_v8n.yaml [--set yolo.epochs=50 model=yolov8s.pt]
python -m vision.eval.two_stage --detector runs/<yolo_run>/best.pt --classifier <clf_run>
```

- `train_yolo.py` : `model.train` d'Ultralytics avec un `DetectionTrainer` dérivé qui applique la **teinte LED** (`batch_augment.led_tint`) à 30 % des images de chaque batch. L'intégration MLflow d'Ultralytics est retirée : paramètres, métriques par epoch, puis mAP@0.5, mAP@0.5:0.95 et rappel par classe sur `test`, dans l'expérience `phase2-detection` de la même base que le classifieur. Poids dans `runs/<run_id>/best.pt`, courbes dans `runs/ultralytics/<run_id>/`.
- `vision/eval/two_stage.py` : YOLO → crops (marge 10 %) → classifieur de la phase 1 (même transformation d'évaluation) ; une scène est « plante anormale » si une feuille dépasse `p_anormal ≥ 0,5`. Évaluation dès maintenant sur **PlantDoc TEST** (labels VOC → `sante` par la taxonomie ; le classifieur n'a jamais vu PlantDoc) : rappel et précision des feuilles (IoU ≥ 0,5), santé des feuilles appariées, rappel « plante anormale » et faux positifs par image. Rapport dans `reports/<clf_run>/two_stage_test.{json,png}`.
- Notebook Colab : `notebooks/05_detection.ipynb`.

## 4. Anomalies non vues — `anomalib` / PatchCore
Pour les problèmes absents des datasets (carences N/K/Mg, brûlures de lumière, stress hydrique, étiolement) :
- entraîner **PatchCore** uniquement sur des images **saines de notre serre**, par espèce ;
- sortie : score d'anomalie et carte de chaleur ;
- seuil calibré sur un lot de validation sain (ex. 99ᵉ percentile).

La première version est donc disponible dès qu'on dispose d'environ 200 images saines par culture.

`vision/anomaly/patchcore.py` : implémentation maison (backbone timm `wide_resnet50_2`, couches 2 et 3, agrégation 3×3, coreset glouton à 10 %, plus proche voisin), sans dépendance à anomalib. Aucun entraînement de réseau : la banque de patchs est construite à partir des images saines.

```bash
python -m vision.anomaly.patchcore fit --images data/serre/sain/tomate --espece tomate   # 20 % réservés au seuil
python -m vision.anomaly.patchcore score --images data/serre/a_verifier --espece tomate
```
Modèle par espèce : `runs/patchcore/<espece>.pt` (banque, seuil, configuration).

## 5. Suivi de croissance
Signal continu par plante (ou par zone), calculé à chaque capture :
1. **Segmentation de la canopée** : indice ExG (`2G − R − B`) + seuillage d'Otsu au départ, puis un modèle de segmentation léger (YOLOv8n-seg) ;
2. indicateurs : surface verte (px, convertie en cm² grâce à une mire de calibration), hauteur (caméra latérale), teinte moyenne et indice de jaunissement ;
3. **courbe de croissance attendue** par culture (logistique, ajustée sur les cycles précédents) ;
4. alerte si l'écart dépasse k·σ pendant N captures consécutives (croissance ralentie, jaunissement progressif).

Implémentation : `vision/growth/canopy.py` (ExG + Otsu, interface `CanopySegmenter` pour brancher YOLOv8n-seg, indicateurs par capture ou par ROI de plante) et `vision/growth/curve.py` (`fit_logistic`, σ des résidus, `growth_alert` : N écarts consécutifs au-delà de k·σ, croissance ralentie seulement par défaut). Les sorties sont des enregistrements plats ; l'écriture dans TimescaleDB relève de l'étape G1.

Ces séries sont stockées dans TimescaleDB, à côté des capteurs, et servent d'entrées au modèle de prévision ([06](06-capteurs-controle.md#4-stratégie-de-contrôle)).
