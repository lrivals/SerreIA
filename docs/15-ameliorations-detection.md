# 15 — Améliorations de la détection et du pipeline deux étages

**But** : transformer les constats de [14](14-resultats-phase1.md) §8 (notebook `05_detection`)
en un plan de travail : quoi faire, dans quel fichier, comment savoir si ça a marché, et dans
quel ordre. Les pistes propres au classifieur (fond, seuil `sante`, calibration, seeds) restent
dans [14](14-resultats-phase1.md) §7 ; elles sont citées ici quand le pipeline en dépend.

## 1. Point de départ

| | valeur | lecture |
|---|---|---|
| mAP@0.5 val / test (PlantDoc + PV) | 0,888 / 0,956 | critère [07](07-roadmap.md) (≥ 0,6) atteint ; test flatté |
| rappel / précision feuille (bout de chaîne) | 0,918 / 0,708 | précision sous-estimée (feuilles non annotées) |
| image : rappel « plante anormale » | 0,979 | |
| **image : faux positifs sur images saines** | **0,422** | **bloquant pour les alertes de la phase 3** |

Trois problèmes de fond :
1. **La mesure n'est pas fiable** : mauvais classifieur évalué (`96f8b511`, ablation E, au lieu
   de `1e8dfc9c`), test mélangé avec PlantVillage, erreurs du détecteur et du classifieur
   mélangées entre elles.
2. **La décision image est trop sensible** : une seule feuille au-dessus de p = 0,5 suffit.
3. **Les données du détecteur ne ressemblent pas à la serre** : annotations PlantDoc
   incomplètes, peu de scènes denses, aucune image réelle.

## 2. Objectifs proposés

À valider ; mesurés sur PlantDoc TEST tant qu'il n'y a pas d'images de la serre annotées.

| métrique | actuel | cible |
|---|---|---|
| faux positifs image (images saines) | 0,42 | **≤ 0,15** |
| rappel « plante anormale » (image) | 0,98 | ≥ 0,90 |
| mAP@0.5 PlantDoc seul (test) | non mesurée | rapportée ; ne pas régresser |
| règle de décision | différente hors ligne / edge | **une seule règle, la même partout** |

Le rappel peut baisser : 0,98 obtenu avec 42 % de fausses alertes n'est pas un acquis.
En serre, le lissage temporel (§4, B1) rattrape une partie du rappel perdu sur une capture.

## 3. Axe A — Mesurer juste (P0, avant tout le reste)

Aucun entraînement : on rejoue l'évaluation avec les poids existants
(`YOLO_RUN = "a604f0445e484b6fa8e44aa45943317e"`).

### A1. Évaluer le classifieur retenu
- **Constat** : `CLF_RUN = None` prend le `best.pt` le plus récent, donc la dernière ablation lancée.
- **Action** : notebook 05, `CLF_RUN = "1e8dfc9cdd014b6bbc246333319dba67"` par défaut ; garder
  l'heuristique « le plus récent » seulement en dernier recours, avec un avertissement qui
  affiche le run choisi.
- **Succès** : `reports/1e8dfc9c…/two_stage_test.json` produit ; tableau de [14](14-resultats-phase1.md)
  §8.4 mis à jour.

### A2. mAP par source
- **Constat** : 29 % des boîtes test viennent de PlantVillage (une feuille sur fond gris) ;
  PlantDoc TEST a 1,9 boîte par image contre 3,3 en val.
- **Action** : `build_yolo_dataset` écrit en plus `data_plantdoc.yaml` (listes d'images
  `test_plantdoc.txt` / `val_plantdoc.txt`) ; `train_yolo.final_metrics` évalue les deux jeux
  et journalise `test/mAP50` et `test_plantdoc/mAP50` (idem `val`) dans MLflow.
- **Succès** : les deux lignes dans MLflow et dans la sortie du notebook. La mAP PlantDoc seule
  devient la métrique de comparaison entre runs YOLO.

### A3. Séparer détecteur, classifieur et contexte
- **Constat** : l'exactitude `sante` sur les crops détectés (0,855) dépasse celle de la phase 1
  sur les crops de vérité (≈ 0,75), sans qu'on sache pourquoi.
- **Action** : dans `vision/eval/two_stage.py`, un mode `--oracle-boxes` qui classe les boîtes
  de vérité à la place des détections, avec `margin` 0 et 0,1. Trois lignes à comparer :
  vérité / marge 0, vérité / marge 0,1, détecteur / marge 0,1.
- **Succès** : on sait si le gain vient de la marge (à garder et à reporter en phase 1), du
  sous-ensemble TEST, ou de la sélection des feuilles faciles par le détecteur.

### A4. Métriques manquantes
- **Action** (`two_stage.evaluate`) :
  - spécificité feuille (`feuilles/specificite`) ;
  - balayage de `seuil_anormal` de 0,3 à 0,95 : rappel image et faux positifs image à chaque
    seuil, enregistrés dans le JSON et tracés en courbe dans le notebook ;
  - IC bootstrap à 95 % sur les deux métriques image (seulement 90 images saines : ±0,10 environ).
- **Audit manuel** : sur 50 « faux positifs » détection tirés au hasard, compter ceux qui sont de
  vraies feuilles non annotées. Cela donne une précision corrigée et justifie (ou non) l'axe C1.

## 4. Axe B — Décision image : réduire les fausses alertes (P1)

Sans réentraîner. Toutes les règles sont réglées sur un jeu de **réglage** distinct du test :
PlantDoc val (scènes de `data/yolo/val`, labels VOC d'origine), pour ne pas sur-ajuster TEST.

### B0. Une seule règle de décision
- **Constat** : hors ligne, `TwoStagePipeline` décide « anormale » si `max p_anormal ≥ 0,5`
  sur une capture ; sur le Pi, `edge.controller.vision_alerts` déclenche à `sante_conf > 0,6`
  sur N = 3 captures consécutives. Les deux ne mesurent pas la même chose.
- **Action** : extraire la règle par capture dans une fonction partagée (`vision/eval/decision.py`
  ou `common/`), appelée par `two_stage.py` et par `abnormal_score` côté edge ; paramètres dans
  `edge/config.yaml`.

### B1. Lissage temporel : mesurer l'existant
- `VisionSmoother` (N = 3, mode `consecutif` ou `moyenne`) existe déjà. Si les fausses alertes
  d'une capture sont indépendantes d'une capture à l'autre, un taux de 0,42 tombe à
  0,42³ ≈ 0,07 ; mais un reflet ou une feuille marquée revient à chaque capture : ce n'est pas
  indépendant.
- **Action** : rejouer l'archive (`--replay edge/archive`) dès qu'il y a quelques jours de
  captures d'une serre saine ; compter les `warning` par jour et par caméra.
- **Succès** : < 1 `warning` par semaine et par caméra sur une serre saine.

### B2. Agrégation des feuilles
Candidats, comparés sur la courbe de A4 au même rappel image :
- **seuil relevé** seul (le plus simple) ;
- **k feuilles** : au moins k ≥ 2 feuilles au-dessus du seuil, ou une seule très au-dessus
  (p ≥ 0,9) ;
- **moyenne des top-k** des `p_anormal` ;
- **pondération** par la confiance de détection et la surface du crop.
Retenir la règle la plus simple qui atteint la cible du §2.

### B3. Écarter les crops inexploitables
- **Action** : avant classification, marquer « non classé » les crops trop petits (côté < 64 px
  à l'échelle source), flous (variance du laplacien sous un seuil réglé sur val) ou coupés par
  le bord de l'image sur plus de 30 % de la boîte.
- **Succès** : faux positifs image en baisse sans perte de rappel ; part de crops écartés
  rapportée (au-delà de ~20 %, le filtre est trop strict).

### B4. Calibration (dépend de [14](14-resultats-phase1.md) §7, point 4)
Les règles B2 manipulent directement `p_anormal` : un temperature scaling du classifieur rend
les seuils transposables d'un modèle à l'autre. À faire avant de figer les seuils de B2.

## 5. Axe C — Des données de détection plus proches de la serre (P2)

### C1. Compléter les annotations PlantDoc
- **Constat** : PlantDoc n'annote que les feuilles porteuses du label ; le détecteur est
  pénalisé quand il trouve les autres, et apprend à les ignorer.
- **Action** : `python -m vision.labeling.pseudo_labels detector --detector
  runs/a604f044…/best.pt --images data/plantdoc/train` (boîtes affinées par SAM 2), import dans
  Label Studio, validation des **seules boîtes ajoutées** (celles sans IoU ≥ 0,5 avec une boîte
  d'origine). `build_yolo_dataset` fusionne ensuite les boîtes validées. Même traitement sur
  val et test, pour que la mesure reste cohérente.
- **Coût** : environ 2 100 images. Commencer par les 500 images au plus grand nombre de boîtes
  ajoutées.
- **Succès** : précision mesurée en hausse sans baisse de rappel ; plus de détections de
  feuilles visibles non encadrées sur la planche d'exemples.

### C2. Images de la serre
- **Action** : dès que les caméras tournent, extraire ~300 captures variées (caméra × heure,
  éclairage LED compris) avec `vision.labeling.active_learning`, pré-annotées par le détecteur,
  validées dans Label Studio (boîtes `feuille`, et `sante` par boîte quand c'est visible).
  Découpage : 1/3 réglage (remplace PlantDoc val pour l'axe B), 2/3 test final.
- **Succès** : second critère de [07](07-roadmap.md) évaluable (pipeline de bout en bout sur
  photos réelles) ; tous les seuils de l'axe B recalés sur ces images.

### C3. Moins de PlantVillage
- **Action** : `PV_PER_CLASS` 40 → 10 (ou 0 pour le test), réentraînement YOLO.
- **Succès** : mAP PlantDoc seule (A2) stable ou en hausse. Si elle baisse, PlantVillage aide
  et on le garde en train seulement.

### C4. Classes `plante` et `fruit`
Prévues dans [04](04-detection-yolo.md) ; à annoter dans C2. Elles permettent d'agréger les
feuilles **par plante** et de rattacher une alerte à un emplacement de [09](09-modele-gestion-serre.md),
qui fournit aussi l'espèce ([14](14-resultats-phase1.md) §7, point 8).

## 6. Axe D — Modèle de détection (P2, après C)

Les pertes train et val baissent encore à l'epoch 100 : un peu de marge, mais mAP@0.5 val est
déjà à ~0,89. À faire **après C1–C2**, qui changent la cible, et en comparant sur la mAP
PlantDoc seule (A2) :

| essai | surcharge | contrainte |
|---|---|---|
| plus long | `yolo.epochs=150 yolo.patience=50` | aucune |
| résolution | `yolo.imgsz=960` | latence Hailo à mesurer ([05](05-edge-deploiement.md)) |
| plus gros | `model=yolov8s.pt` | ~3× les FLOPs de v8n ; latence Hailo |
| alternative | `model=yolo11n.pt` | support Hailo Model Zoo à vérifier |

Un seul facteur à la fois ; garder v8n tant que le gain PlantDoc seul est < 0,02 (de l'ordre de
la variance d'un run à l'autre en phase 1).

## 7. Ordre proposé

| étape | contenu | réentraînement | dépend de |
|---|---|---|---|
| 1 | A1, A2, A3, A4 | non (A2 : réévaluation seulement) | — |
| 2 | B0, B2, B3 sur PlantDoc val | non | 1 |
| 3 | B4 (calibration classifieur) puis seuils figés | non (post-hoc) | 2 |
| 4 | C1 (annotations PlantDoc), C3, réentraînement YOLO | oui | 1 |
| 5 | C2 (images serre), recalage des seuils B, B1 sur l'archive | oui | caméras en place |
| 6 | D | oui | 4, 5 |

Les étapes 1 à 3 tiennent dans le notebook 05 et `two_stage.py`, sans GPU long ; elles devraient
à elles seules faire passer les faux positifs image sous la cible.

## 8. Ce qu'on ne fait pas maintenant
- **Changer d'architecture de détecteur** avant d'avoir une mesure propre (A) et des données
  plus proches de la serre (C) : le détecteur n'est pas le maillon faible.
- **Optimiser encore sur PlantDoc TEST** : 90 images saines seulement ; au-delà des étapes 1–3,
  les gains ne seront pas mesurables. La suite se mesure sur les images de la serre (C2).
