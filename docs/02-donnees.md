# 02 — Données

## 1. État réel du dossier `data/`

Inspection du 12/10/2026, corrections faites le jour même :

| Dossier d'origine | Contenu réel | Images | Action | État |
|---|---|---|---|---|
| `PlantVillage Dataset/` | **ASL Alphabet** (A–Z, `space`, `del`, `nothing`) : mauvais téléchargement | 87 028 | supprimer | ✅ |
| `PlantDoc Dataset/plantvillage dataset/` | **PlantVillage** : 38 classes, sous-dossiers `color/`, `grayscale/`, `segmented/` | 54 305 (color) | déplacer vers `data/plantvillage/` | ✅ |
| `Dataset for Crop Pest and Disease Detection/` | **CCMT** : 4 cultures, 22 classes, `Raw Data/` + `CCMT Dataset-Augmented/` | 26 220 (raw) | `data/ccmt/raw` (+ `augmented`, inutilisé) | ✅ |
| `PlantDoc-Object-Detection-Dataset-master/` | **PlantDoc** détection (images au champ, VOC XML) | 2 598 images, 8 710 boîtes | `data/plantdoc/{train,test}` + crops | ✅ |

Commandes (idempotentes, rien n'est supprimé) :
```bash
python -m vision.datasets.prepare ccmt
python -m vision.datasets.prepare plantdoc --src data/PlantDoc-Object-Detection-Dataset-master
python -m vision.datasets.build_index          # ~40 s sur 22 cœurs, cache dans data/.cache/
```

Arborescence cible :
```
data/
├── plantvillage/{color,segmented}/<Espece>___<Etat>/
├── ccmt/raw/<Culture>/<classe>/
├── plantdoc/{train,test}/            # images + annotations VOC (XML)
├── plantdoc/crops/{train,test}/<label>/  # une image par boîte (≥ 32 px), pour le classifieur
├── backgrounds/                      # fonds de serre (voir 03-classifieur)
└── index.parquet
```

PlantDoc : récupérer la version **détection** (dépôt GitHub `pratikkayal/PlantDoc-Object-Detection-Dataset`, annotations VOC XML). Elle sert à la fois au test cross-domain du classifieur (via des crops des boîtes) et à l'entraînement YOLO.

> **Pourquoi « Raw » pour CCMT ?** La version augmentée contient des transformations des mêmes images réparties entre `train_set` et `test_set` : c'est une fuite garantie. On applique notre propre augmentation, à la volée.

### Inventaire PlantVillage (color)
14 espèces : Apple, Blueberry, Cherry, Corn, Grape, Orange, Peach, Pepper, Potato, Raspberry, Soybean, Squash, Strawberry, Tomato.
Déséquilibres notables : `Orange___Haunglongbing` 5 507, `Tomato_Yellow_Leaf_Curl_Virus` 5 357, `Soybean___healthy` 5 090, contre `Potato___healthy` 152 et `Apple___Cedar_apple_rust` 275.

### Inventaire CCMT (raw)
| Culture | Classes (effectifs) |
|---|---|
| Cashew (6 549) | anthracnose 1729, gumosis 392, healthy 1368, leaf miner 1378, red rust 1682 |
| Cassava (7 508) | bacterial blight 2614, brown spot 1481, green mite 1015, healthy 1193, mosaic 1205 |
| Maize (5 358) | fall armyworm 285, grasshoper 673, healthy 208, leaf beetle 948, leaf blight 1006, leaf spot 1259, streak virus 979 |
| Tomato (6 805) | healthy 470, leaf blight 1301, leaf curl 518, septoria leaf spot 2743, verticulium wilt 773 |

Total exploitable pour la phase 1 : **≈ 80 500 images, 16 espèces**.

## 2. Taxonomie unifiée — `vision/datasets/taxonomy.yaml`

Chaque dossier source est associé à trois niveaux :
- `espece` : nom en français, minuscules (`tomate`, `mais`, `manioc`, `anacardier`, …) ;
- `etat` : `sain | maladie | nuisible | carence | virus` (agrégé en `sante` = `sain | anormal`) ;
- `classe` : identifiant fin `espece/etat/nom`.

```yaml
version: 1
classes:
  tomate/sain/sain:
    sources:
      plantvillage: ["Tomato___healthy"]
      ccmt: ["Tomato/healthy"]
      plantdoc: ["Tomato leaf"]
  tomate/maladie/septoriose:
    sources:
      plantvillage: ["Tomato___Septoria_leaf_spot"]
      ccmt: ["Tomato/septoria leaf spot"]
      plantdoc: ["Tomato Septoria leaf spot"]
  tomate/maladie/mildiou:
    sources:
      plantvillage: ["Tomato___Late_blight"]
      plantdoc: ["Tomato leaf late blight"]
  tomate/maladie/brulure_ccmt:          # "leaf blight" CCMT : early ou late ? ambigu
    ambigu: true
    sources:
      ccmt: ["Tomato/leaf blight"]
  tomate/nuisible/tetranyque:
    sources:
      plantvillage: ["Tomato___Spider_mites Two-spotted_spider_mite"]
  mais/maladie/helminthosporiose:
    sources:
      plantvillage: ["Corn_(maize)___Northern_Leaf_Blight"]
      ccmt: ["Maize/leaf blight"]
      plantdoc: ["Corn leaf blight"]
  mais/nuisible/chenille_legionnaire:
    sources:
      ccmt: ["Maize/fall armyworm"]
  # ...
```

Règles :
1. **On ne fusionne deux classes que si c'est botaniquement sûr.** Sinon, on garde des classes séparées marquées `ambigu: true`. Elles comptent pour `espece` et `sante`, mais leur métrique `classe` est rapportée à part.
2. Les labels PlantDoc sont vérifiés après le téléchargement (`prepare plantdoc` les liste et signale ceux qui ne sont pas mappés) : ils diffèrent légèrement d'une version à l'autre. Version actuelle : 29 labels, tous mappés.
3. Toute modification incrémente `version`, qui est enregistrée dans chaque run MLflow.

Résultat : **16 espèces, 56 classes fines (dont 3 `ambigu`), 2 classes de santé**.

## 3. Index — `vision/datasets/build_index.py`

Produit `data/index.parquet`, une ligne par image :

| Colonne | Type | Description |
|---|---|---|
| `path` | str | chemin relatif à `data/` |
| `source` | cat | `plantvillage` / `ccmt` / `plantdoc` / `serre` |
| `espece`, `etat`, `classe` | cat | issus de la taxonomie |
| `sante` | cat | `sain` / `anormal` |
| `ambigu` | bool | |
| `width`, `height` | int | |
| `phash` | uint64 | hash perceptuel (`imagehash.phash`) |
| `dhash` | uint64 | hash de gradient (`imagehash.dhash`), confirme les paires pHash |
| `groupe` | int | identifiant de groupe de quasi-doublons |
| `split` | cat | `train` / `val` / `test` / `test_xdomain` |
| `mask_path` | str? | masque PlantVillage `segmented/` si disponible |

Étapes :
1. Parcours des sources et application de la taxonomie. Un dossier non mappé est une **erreur** (pas d'oubli silencieux).
2. Lecture de l'image (rejet des fichiers corrompus, journalisés) et calcul du pHash et du dHash.
3. **Groupement des quasi-doublons** : distance de Hamming ≤ 6 entre pHash **et** ≤ 8 entre dHash → même `groupe` (union-find ; candidats trouvés par buckets, principe des tiroirs sur 7 blocs de bits). PlantVillage contient plusieurs prises de la même feuille.
   > **Pourquoi la confirmation dHash ?** Avec le pHash seul, les feuilles PlantVillage sur fond uni se ressemblent assez pour que l'union-find les chaîne en un groupe géant de 4 623 images (distance médiane interne : 26 bits ; soja, oranger, anacardier mélangés). La distance dHash des paires candidates est bimodale : ≤ 8 pour les vrais doublons, au-delà pour le reste. Avec la confirmation, le plus gros groupe compte 21 images.
4. **Splits groupés et stratifiés** (`StratifiedGroupKFold` sur `classe`, avec `groupe` comme groupe) : 80 / 10 / 10 pour PlantVillage + CCMT.
5. **PlantDoc → `test_xdomain` uniquement** (jamais vu à l'entraînement en phase 1). Un crop PlantDoc groupé avec une image PlantVillage/CCMT est exclu, car il contaminerait `test_xdomain`, et journalisé avec les rejets (2 cas : des photos de stock sur fond blanc).
6. Rapport console : effectifs par source, split et classe ; nombre de groupes ; fichiers rejetés (liste aussi dans `data/index_rejets.txt`). La version de la taxonomie est enregistrée dans les métadonnées du parquet.

### Résultat (12/10/2026)

| Source | train | val | test | test_xdomain |
|---|---|---|---|---|
| PlantVillage | 43 434 | 5 432 | 5 439 | — |
| CCMT | 20 111 | 2 511 | 2 504 | — |
| PlantDoc (crops) | — | — | — | 8 704 |

Points d'attention :
- **94 fichiers CCMT corrompus** (Maize 69, Tomato 25 ; dont 4 dans `Tomato/healthy`), exclus.
- **CCMT contient la même image dans plusieurs classes** : 229 hash identiques entre classes, surtout `Maize/leaf blight` ↔ `Maize/leaf spot` ↔ `Maize/streak virus`. C'est du bruit d'étiquetage : le groupement les place dans le même split, mais leurs étiquettes restent contradictoires. Il faudra les dédoublonner ou les écarter avant l'entraînement.
- `pomme_de_terre/sain` est très faible : 15 images en val et 15 en test (alerte sous 20).

Contrôles automatiques (dans `tests/`) :
- aucun `groupe` présent dans deux splits ;
- les effectifs CCMT et PlantVillage correspondent aux comptes des dossiers (ex. `ccmt/raw/Tomato/healthy` = 470) ;
- toutes les classes ont au moins N images en `val` et en `test`, sinon un avertissement est émis.

## 4. Données propres à la serre (plus tard)

Les images issues de nos caméras entrent dans l'index avec `source = serre`, une fois annotées dans Label Studio (voir [05-edge-deploiement](05-edge-deploiement.md#5-boucle-dapprentissage-actif)). C'est la voie d'ajout de **fraise, salades et aromatiques**, qui sont absentes ou très peu représentées dans les datasets publics.

## 5. Licences

| Dataset | Licence (à vérifier sur la page source) |
|---|---|
| PlantVillage | CC BY-SA 3.0 (version Kaggle/GitHub spMohanty) |
| PlantDoc | CC BY 4.0 |
| CCMT (Mendeley Data) | CC BY 4.0 |

Usage personnel ou de recherche : OK. En cas de publication, citer les auteurs.
