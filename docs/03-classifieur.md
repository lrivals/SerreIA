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
| Classes ambiguës | exclues de la loss `classe`, conservées pour `espece` et `sante` |
| Déséquilibre | `WeightedRandomSampler` (poids ∝ 1/√effectif de la classe) |
| Optimiseur | AdamW, lr 1e-3 (têtes) / 3e-4 (backbone), weight decay 0,05 |
| Planning | 2 epochs avec backbone gelé, puis fine-tuning complet ; cosine + warmup ; 25–30 epochs |
| Batch | 64, AMP fp16 (adapté aux 6 Go de VRAM) |
| Résolution | 224 (puis essai à 256 / 288 si le gain cross-domain le justifie) |
| Sélection du modèle | meilleur **F1 macro `sante` sur `val`** + suivi du F1 `classe` |
| Seed | fixée, enregistrée |

Configuration en YAML (`configs/clf_effnet_b0.yaml`). Chaque run est enregistré dans **MLflow** : config, version de la taxonomie, hash de l'index, métriques et artefacts (matrices, Grad-CAM, poids).

## 3. Écart de domaine : le cœur du travail

PlantVillage montre une feuille isolée sur fond uni, sous une lumière homogène. La serre offre au contraire un feuillage dense, un fond encombré et un éclairage LED horticole (rose/violet). Un modèle naïf atteint environ 99 % sur PlantVillage et s'effondre sur des images réelles. Trois leviers permettent de l'éviter.

### 3.1 Augmentations (`vision/datasets/augment.py`, albumentations)
- géométriques : `RandomResizedCrop(scale=0.3–1.0)`, flips, rotation ±30°, perspective ;
- photométriques : `ColorJitter` fort, **variation de teinte simulant les LED** (gain R/B), `RandomGamma`, `CLAHE` ;
- dégradations : flou de mouvement ou gaussien, bruit ISO, compression JPEG (qualité 30–90), ombres aléatoires ;
- `CoarseDropout` (occlusions par d'autres feuilles).

### 3.2 Remplacement de fond (contribution originale)
PlantVillage fournit `segmented/`, des versions détourées qui permettent d'extraire les masques.
1. Constituer `data/backgrounds/` : photos de serre, de feuillage, de terreau, de bacs hydroponiques (les nôtres, plus des images libres de droits).
2. Avec une probabilité p = 0,5, coller la feuille masquée sur un fond aléatoire (léger flou des bords, harmonisation des couleurs).
3. Variante « multi-feuilles » : coller 2 à 4 feuilles ; seule la feuille principale porte l'étiquette.

C'est l'ablation la plus importante à mesurer (avec et sans), voir §4.

### 3.3 Grad-CAM comme garde-fou
Si les cartes d'attention tombent sur le fond ou les bords, le modèle exploite un raccourci : il faut renforcer le remplacement de fond.

## 4. Évaluation — `vision/eval/cross_domain_eval.py`

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

Livrable : `reports/phase1.md`, avec le tableau des ablations, les matrices et une planche Grad-CAM.

## 5. Explicabilité — `vision/eval/gradcam.py`
- Grad-CAM (ou Grad-CAM++) sur la dernière couche convolutive, pour chaque tête ;
- planche de 32 exemples par source (bonnes et mauvaises prédictions) ;
- les cartes sont réutilisées comme **pré-annotations** pour YOLO (voir [04](04-detection-yolo.md#2-annotation-semi-automatique)).

## 6. Critères de sortie de la phase 1
- F1 `sante` in-domain ≥ 0,97 ;
- **rappel « anormal » sur PlantDoc ≥ 0,80** (objectif réaliste ; la littérature rapporte de fortes chutes cross-domain) ;
- export ONNX validé (écart < 0,5 point par rapport à PyTorch).
