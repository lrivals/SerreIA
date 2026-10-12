# 04 — Phase 2 : détection YOLO et anomalies de croissance

Le classifieur répond à la question « cette image est-elle malade ? ». Dans la serre, une caméra voit **plusieurs plantes et des dizaines de feuilles** : il faut **localiser**. Il faut aussi détecter ce qu'aucun dataset ne contient (carences, stress hydrique, croissance anormale).

## 1. Architecture deux étages (recommandée)

```
image caméra ──► YOLO (détecteur générique) ──► boîtes « feuille » / « plante » / « fruit »
                                                    │ crop
                                                    ▼
                                         classifieur phase 1 ──► espece / sante / classe
```

Pourquoi ce choix plutôt qu'un YOLO à 55 classes :
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

## 3. Entraînement — `vision/train/train_yolo.py`
- base : poids COCO ; augmentations Ultralytics (mosaic, HSV) + teinte LED ;
- splits **groupés** (même logique qu'en [02](02-donnees.md#3-index--visiondatasetsbuild_indexpy)) ;
- métriques : mAP@0.5, mAP@0.5:0.95, rappel par classe ;
- évaluation finale de bout en bout : **détection + classification** sur des images de la serre annotées (rappel « plante anormale » par image).

## 4. Anomalies non vues — `anomalib` / PatchCore
Pour les problèmes absents des datasets (carences N/K/Mg, brûlures de lumière, stress hydrique, étiolement) :
- entraîner **PatchCore** uniquement sur des images **saines de notre serre**, par espèce ;
- sortie : score d'anomalie et carte de chaleur ;
- seuil calibré sur un lot de validation sain (ex. 99ᵉ percentile).

La première version est donc disponible dès qu'on dispose d'environ 200 images saines par culture.

## 5. Suivi de croissance
Signal continu par plante (ou par zone), calculé à chaque capture :
1. **Segmentation de la canopée** : indice ExG (`2G − R − B`) + seuillage d'Otsu au départ, puis un modèle de segmentation léger (YOLOv8n-seg) ;
2. indicateurs : surface verte (px, convertie en cm² grâce à une mire de calibration), hauteur (caméra latérale), teinte moyenne et indice de jaunissement ;
3. **courbe de croissance attendue** par culture (logistique, ajustée sur les cycles précédents) ;
4. alerte si l'écart dépasse k·σ pendant N captures consécutives (croissance ralentie, jaunissement progressif).

Ces séries sont stockées dans TimescaleDB, à côté des capteurs, et servent d'entrées au modèle de prévision ([06](06-capteurs-controle.md#4-stratégie-de-contrôle)).
