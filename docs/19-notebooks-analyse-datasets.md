# 19 — Notebooks d'analyse des datasets

**But** : décrire trois notebooks qui donnent une vue statistique détaillée de chaque jeu de
données du projet : leur composition, leur qualité et leurs biais. Ces chiffres doivent
alimenter les choix d'entraînement ([03](03-classifieur.md), [04](04-detection-yolo.md)) et
de prévision ([09](09-modele-gestion-serre.md)).

Aujourd'hui, `notebooks/01_donnees.ipynb` ne montre que les effectifs source × split et
classe × split, des exemples d'images et les augmentations. Rien ne couvre le jeu de détection
`data/yolo/` ni les séries des capteurs.

| Notebook | Jeu | Source des données | Priorité |
|---|---|---|---|
| `06_stats_classifieur` | index du classifieur (≈ 80 k images, 56 classes) | `data/index.parquet` + images | P1 |
| `07_stats_yolo` | jeu de détection (4 427 images) | `data/yolo/` (`manifest.parquet`, `labels/`) | P1 |
| `08_stats_capteurs` | séries temporelles capteurs et actionneurs | `data/scenarios/*/serre.db`, `sim.dataset.generate` | P2 |

Le plan complète [02](02-donnees.md) (construction de l'index) et
[18](18-ameliorations-logicielles.md) sans les répéter. Priorités et efforts suivent la
convention de [18 §1](18-ameliorations-logicielles.md#1-principes).

## 1. Contraintes communes

- **Générés, jamais édités** : les trois notebooks sont ajoutés à `NOTEBOOKS` dans
  `tools/notebooks/build.py` (`make notebooks`) et contrôlés par `tests/test_notebooks.py`
  (`--check`). Ils sont committés **sans sorties**.
- **Structure fixe**, la même que 01 à 05 : titre et badge Colab, cellule `parameters`
  compatible papermill, cellule d'environnement (`drive_data.ensure([...])`, voir
  [data-drive](data-drive.md)), corps, résumé.
- **Pas de calcul dans les cellules** : elles appellent des fonctions du dépôt et affichent
  le résultat. Le calcul vit dans des modules testés (§2).
- **Sans GPU** : CPU seulement, métadonnées `gpu=False`. Les mesures sur les pixels
  travaillent sur un échantillon stratifié (`N_SAMPLE`) pour tenir en quelques minutes sur
  Colab.
- **Sorties persistées** : chaque notebook écrit `reports/datasets/<jeu>/` avec
  `summary.json` (chiffres clés, version de la taxonomie, date, hash de l'index),
  `summary.md` et des figures PNG. Sur Colab, ce dossier est synchronisé comme `reports/` ;
  sur le PC, il est récupéré par `make harvest`.

## 2. Architecture : calcul dans des modules, affichage dans les notebooks

| Module (nouveau) | Contenu | Réutilise |
|---|---|---|
| `vision/datasets/stats.py` | statistiques de l'index et du jeu YOLO : effectifs, déséquilibre, couverture, cohérence des splits, photométrie, doublons, boîtes | `load_index`, `drop_contradictory_groups`, `stratified_subset`, `read_rgb` (`vision/datasets/dataset.py`), `DATA_DIR`, `INDEX_NAME` (`build_index.py`), `Taxonomy` (`taxonomy.py`) |
| `sim/stats.py` | statistiques des séries : lecture SQLite en table large, couverture et trous, profils journaliers, corrélations, cycles des actionneurs | `sim.dataset.generate`, schéma `mesure` / `etat_actionneur` / `alerte` (`backend`) |

Règles :
- chaque fonction prend un `DataFrame` (ou un chemin SQLite) et rend un `DataFrame` ou un
  `dict` sérialisable : testable sur des données synthétiques ;
- les tracés (`matplotlib`) sont dans une petite couche `plot_*` à part, appelée seulement
  par les notebooks ;
- les seuils (alerte d'effectif, trou de capteur, bornes physiques) sont des paramètres avec
  des valeurs par défaut documentées, pas des constantes enfouies.

## 3. Notebook 06 — `06_stats_classifieur`

Paramètres : `N_SAMPLE = 4000` (images pour la photométrie), `MIN_VAL_TEST = 20`,
`CLF_RUN = None` (embeddings optionnels), `SEED = 0`.
Données : `index`, `plantvillage`, `ccmt`, `plantdoc`.

### 3.1 Effectifs et déséquilibre
- tableaux source × split, espèce × split, classe × split (avec et sans les groupes
  contradictoires écartés par `load_index`) ;
- courbe de longue traîne : effectif par classe trié, en échelle log, colorée par source ;
- indicateurs par niveau (`espece`, `classe`, `sante`) : ratio max/min, entropie normalisée,
  coefficient de Gini, nombre effectif de classes (`exp(entropie)`) ;
- classes sous `MIN_VAL_TEST` en val ou en test : aujourd'hui `pomme_de_terre/sain`
  (15 / 15, voir [02 §3](02-donnees.md#3-index--visiondatasetsbuild_indexpy)).

### 3.2 Couverture de la taxonomie
- matrice classe × source (effectifs, puis part de chaque source dans la classe) ;
- liste des **classes mono-source**. Le modèle peut y apprendre « fond uni PlantVillage →
  telle classe » plutôt que le symptôme : ce sont elles à surveiller en cross-domain ;
- classes `ambigu` (3) et leur poids ;
- part des images avec `mask_path` (masques PlantVillage `segmented/`, utilisés par le
  remplacement de fond).

### 3.3 Cohérence des splits
- distance de Jensen-Shannon entre les distributions de classes de train, val et test,
  et test du χ² par source ;
- contrôle redondant de [02](02-donnees.md) : aucun `groupe` dans deux splits (doit
  afficher 0) ;
- `test_xdomain` : classes PlantDoc absentes du train, et inversement.

### 3.4 Géométrie
- distributions de `width`, `height` et du ratio d'aspect par source ;
- part des images plus petites que la résolution d'entrée (224 px), qui seront agrandies.

### 3.5 Photométrie et écart de domaine
Sur `N_SAMPLE` images (échantillon stratifié par source et classe) :
- luminosité moyenne, contraste (écart type de la luminance), saturation et teinte
  dominante (HSV) ;
- netteté : variance du laplacien ;
- **part de fond uni** : fraction des pixels de bordure proches de leur médiane ;
- vue d'ensemble : boîtes à moustaches par source et projection 2D (PCA) de ces
  descripteurs colorée par source.

Objectif : **quantifier l'écart PlantVillage / CCMT vs PlantDoc** (`test_xdomain`) qui
explique la chute cross-domain ([14](14-resultats-phase1.md)), et vérifier que les
augmentations fortes ([03 §3](03-classifieur.md)) couvrent la plage de PlantDoc. On peut
tracer les mêmes descripteurs sur un batch augmenté pour comparer.

### 3.6 Quasi-doublons et bruit d'étiquetage
- distribution de la taille des groupes (le plus gros doit rester à 21) ;
- histogramme des distances pHash et dHash des paires candidates : il doit montrer la
  bimodalité qui justifie le seuil dHash ≤ 8 ([02 §3](02-donnees.md#3-index--visiondatasetsbuild_indexpy)) ;
- groupes contradictoires (même image dans plusieurs classes, surtout CCMT
  `Maize/leaf blight` ↔ `leaf spot` ↔ `streak virus`) : nombre, paires de classes en
  cause, planche d'exemples ;
- fichiers rejetés (`data/index_rejets.txt`) par source et par classe.

### 3.7 Embeddings (P2, optionnel)
Si `CLF_RUN` est fourni : extraction des features du `best.pt` sur l'échantillon, puis UMAP
(ou t-SNE) coloré par source puis par classe. Une séparation nette par source dans une même
classe signale un raccourci de domaine. Seule cellule qui profite d'un GPU ; elle est sautée
si `CLF_RUN` vaut `None`.

## 4. Notebook 07 — `07_stats_yolo`

Paramètres : `IMG_SIZE = 640`, `N_EXAMPLES = 8`, `SEED = 0`. Données : `yolo` (ou
reconstruit par `build_yolo_dataset`, voir [04 §2](04-detection-yolo.md)).

État actuel, relevé le 17/10/2026 dans `manifest.parquet` et `labels/` :

| Source | train | val | test | Total |
|---|---|---|---|---|
| PlantDoc | 2 105 | 235 | 237 | 2 577 |
| PlantVillage | 1 480 | 185 | 185 | 1 850 |
| **Boîtes** | 9 157 | 949 | 637 | 10 743 |

> ⚠️ Les 10 743 boîtes sont **toutes de classe 0 (`feuille`)** : `plante` et `fruit` sont
> déclarées dans `data.yaml` mais n'ont aucune annotation. 11 images n'ont aucune boîte.
> Le notebook doit l'afficher en tête, parce que les métriques par classe du détecteur n'ont
> de sens que pour `feuille`.

### 4.1 Effectifs
- images et boîtes par split × source × classe ;
- images sans boîte (négatifs) : nombre et exemples ;
- cohérence `n_boxes` du manifest ↔ lignes des fichiers `labels/*.txt`.

### 4.2 Géométrie des boîtes
- distribution du nombre de boîtes par image, par source (PlantVillage : une feuille par
  image, PlantDoc : plusieurs) ;
- aire relative, largeur, hauteur et ratio d'aspect des boîtes ;
- catégories COCO `small` / `medium` / `large` après mise à l'échelle à `IMG_SIZE` : part
  de petits objets, là où la mAP chute ;
- carte de chaleur des centres des boîtes (biais de cadrage centré de PlantVillage).

### 4.3 Qualité des annotations
- IoU entre boîtes d'une même image : doublons probables (IoU > 0,9) et boîtes imbriquées ;
- boîtes dégénérées (largeur ou hauteur < 2 px à `IMG_SIZE`) ou débordant de l'image ;
- fuite : aucun `groupe` dans deux splits. La colonne est vide pour les 1 850 images
  PlantVillage, dont la fuite n'est donc pas contrôlée. Il faut le signaler, ou joindre
  `index.parquet` par `path` pour récupérer leur groupe.

### 4.4 Exemples
Planches par split avec boîtes dessinées. Elles remplacent les `preview_*.png` fixes de
`data/yolo/` par une sélection paramétrable (`SEED`, source).

## 5. Notebook 08 — `08_stats_capteurs`

Paramètres : `SOURCE = "scenario:journee"` (`scenario:<nom>`, `sim` ou, plus tard, le
chemin de la base réelle), `SIM_DAYS = 30`, `SIM_SEED = 0`, `GAP_FACTOR = 2`,
`FUSEAU = "Europe/Paris"`. Données : aucune archive Drive. Les scénarios sont dans le dépôt
et `sim` est généré à la volée.

Ce qui existe aujourd'hui :

| Source | Durée | Cadence | Mesures | Zones / types |
|---|---|---|---|---|
| `scenario:journee` | ≈ 28 h | 30 s | 53 608 | z1 : T°, HR, CO₂, lux, pression, présence, humidité du sol (2 sondes) ; z2 (hydro) : T°, HR, lux, pression, pH, EC, T° eau, niveau de cuve |
| `scenario:mildiou` | ≈ 75 h | 30 s | ≈ 144 k | idem |
| `sim` (`sim.dataset.generate`) | `SIM_DAYS` | 10 min | table large | colonnes capteurs, `etat_<actionneur>`, `t_ext` |

### 5.1 Couverture et qualité
- période, cadence médiane par capteur, nombre et durée des **trous** (écart >
  `GAP_FACTOR` × cadence) ;
- part de mesures par valeur de `qualite`. Les scénarios n'ont que `ok` : le notebook doit
  le dire et non conclure à une absence de défaut. Les pannes simulées (`sim/faults.py`)
  sont à injecter pour vérifier que les statistiques les révèlent.

### 5.2 Distributions
- histogrammes et résumés (min, quantiles, max) par `type` × `zone` ;
- valeurs hors bornes physiques (ex. HR hors 0–100 %, pH hors 0–14) ;
- valeurs aberrantes par z-score robuste (médiane, MAD) sur fenêtre glissante.

### 5.3 Dynamique temporelle
- profil journalier en heure locale (médiane et IQR par heure) pour T°, HR, lux, CO₂ ;
- DLI par jour (même conversion lux → PPFD que la serre, `lux_vers_ppfd`) ;
- autocorrélation et décomposition jour/tendance : horizon utile pour la prévision de
  niveau 2 ([11](11-agent-decision.md)) ;
- corrélations entre capteurs d'une zone, et avec `t_ext` pour `sim`.

### 5.4 Actionneurs, alertes, vision
- taux d'activation (duty cycle) et durées des cycles par actionneur (`etat_actionneur`) ;
- délai commande → effet : corrélation croisée entre l'état d'un actionneur et la dérivée du
  capteur visé (ventilateur → T°, brumisateur → HR, pompe → humidité du sol) ;
- alertes par niveau, source et zone sur une frise temporelle ;
- `vision_resultat` : nombre d'analyses par zone, distribution des confiances et de `sante`
  (scénario `mildiou`).

## 6. Effet sur `01_donnees`

`01_donnees` reste un aperçu rapide : effectifs, exemples, augmentations, remplacement de
fond. Son introduction renvoie vers `06_stats_classifieur` pour le détail. Aucune cellule
n'est dupliquée entre les deux.

## 7. Plan de travail

| ID | Item | Priorité | Effort | Fichiers |
|---|---|---|---|---|
| D1 | statistiques de l'index : effectifs, déséquilibre, couverture, splits, géométrie, doublons (§3.1–3.4, §3.6) | P1 | M | `vision/datasets/stats.py`, `tests/test_dataset_stats.py` |
| D2 | photométrie et écart de domaine (§3.5) | P1 | M | `vision/datasets/stats.py` |
| D3 | notebook `06_stats_classifieur` et `reports/datasets/classifieur/` | P1 | S | `tools/notebooks/build.py` |
| D4 | statistiques YOLO (§4) | P1 | S | `vision/datasets/stats.py`, `tests/test_dataset_stats.py` |
| D5 | notebook `07_stats_yolo` | P1 | S | `tools/notebooks/build.py` |
| D6 | lecture SQLite en table large, couverture, distributions, profils, actionneurs (§5) | P2 | M | `sim/stats.py`, `tests/test_sim_stats.py` |
| D7 | notebook `08_stats_capteurs` | P2 | S | `tools/notebooks/build.py` |
| D8 | embeddings UMAP (§3.7) | P2 | S | `vision/datasets/stats.py`, extra `umap-learn` |
| D9 | renvoi de `01_donnees` vers 06 et ligne dans [07](07-roadmap.md) | P2 | S | `tools/notebooks/build.py`, `docs/07-roadmap.md` |

Ordre : D1 → D4 → D3 → D5 (sans pixels), puis D2, puis D6–D7. Le notebook 08 passe en P1
dès que la base réelle de la serre existe.

## 8. Vérification

- **Tests unitaires sur données synthétiques** (`pytest`) : petits `DataFrame` d'index
  fabriqués à la main (déséquilibre connu, un groupe partagé entre splits, une classe
  mono-source), images numpy générées pour la photométrie, base SQLite temporaire avec un
  trou et une valeur hors bornes. Chaque statistique a au moins un test qui vérifie une
  valeur exacte.
- **Notebooks** : `python -m tools.notebooks.build --check` vert, sorties vides.
- **Exécution réelle** (PC ou Colab, par l'utilisateur) : les chiffres doivent recouper
  [02](02-donnees.md) : PlantVillage train 43 434, CCMT train 20 111, crops PlantDoc 8 704,
  plus gros groupe 21 images, `pomme_de_terre/sain` à 15 en val et en test. Pour le jeu YOLO :
  4 427 images et 10 743 boîtes.

## 9. Questions auxquelles les notebooks doivent répondre

| Question | Notebook | Décision qui en dépend |
|---|---|---|
| Quelles classes ne viennent que d'une source ? | 06 §3.2 | classes à rapporter à part en cross-domain, priorités d'annotation de la serre |
| De combien PlantDoc s'écarte-t-il en luminosité, saturation, netteté et fond ? | 06 §3.5 | réglage des augmentations, collecte de `data/backgrounds/` |
| Faut-il retirer ou réétiqueter les groupes contradictoires CCMT ? | 06 §3.6 | nettoyage de l'index (taxonomie v+1) |
| `plante` et `fruit` sont-elles utiles sans annotation ? | 07 | retirer ces classes de `data.yaml` ou lancer leur annotation (Label Studio) |
| Quelle part de petites boîtes ? | 07 §4.2 | taille d'entrée (640 vs 960), tuilage |
| Quel horizon de prévision les autocorrélations justifient-elles ? | 08 §5.3 | paramètres du niveau 2 |
| Quels seuils de trous et de valeurs aberrantes retenir ? | 08 §5.1–5.2 | `capteur_muet_s` et filtres du contrôleur ([18](18-ameliorations-logicielles.md)) |
