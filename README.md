# SerreIA — Serre autonome et intelligente

Système de surveillance et de pilotage d'une serre :
- **capteurs** (température, humidité, CO₂, lumière, pH et EC de la solution nutritive, niveau d'eau) ;
- **actionneurs** (pompes, éclairage LED, ventilation, brumisation) ;
- **caméras** utilisées comme **source d'information continue** pour un modèle de vision qui détecte maladies, nuisibles et anomalies de croissance ;
- **réseaux de neurones** pour la vision et, progressivement, pour l'anticipation et le pilotage.

> **Première contribution majeure** : un modèle de vision spécialisé entraîné sur des datasets publics (PlantVillage, CCMT, PlantDoc).
> On commence par un **classifieur**, puis on passe à la **détection YOLO** avec annotation semi-automatique.

Choix structurants :
- **Modèle généraliste** couvrant toutes les espèces des datasets. Fraise, salades et aromatiques seront ajoutées ensuite avec nos propres images.
- **Matériel embarqué : Raspberry Pi 5 + AI Kit Hailo** (inférence) et nœuds **ESP32** (capteurs et actionneurs).
- **Bus de communication unique : MQTT** (JSON). Le logiciel et l'électronique avancent ainsi indépendamment.

## Sommaire de la documentation

| # | Document | Contenu |
|---|---|---|
| 01 | [Architecture](docs/01-architecture.md) | Vue d'ensemble, contrat MQTT, organisation du dépôt |
| 02 | [Données](docs/02-donnees.md) | État des datasets, corrections, taxonomie unifiée, index, splits |
| 03 | [Classifieur](docs/03-classifieur.md) | Phase 1 : modèle multi-têtes, écart de domaine, évaluation, explicabilité |
| 04 | [Détection YOLO et anomalies](docs/04-detection-yolo.md) | Phase 2 : YOLO deux étages, annotation, PatchCore, suivi de croissance |
| 05 | [Edge et déploiement](docs/05-edge-deploiement.md) | Pi 5 + Hailo, export ONNX → HEF, service caméra, apprentissage actif |
| 06 | [Capteurs et contrôle](docs/06-capteurs-controle.md) | Électronique, firmware ESP32, stratégie de contrôle, simulateur |
| 07 | [Feuille de route](docs/07-roadmap.md) | Étapes, critères de validation, risques |
| 08 | [Environnement](docs/08-environnement.md) | Installation, dépendances, conventions |
| 09 | [Modèle de gestion de serre](docs/09-modele-gestion-serre.md) | Zones, emplacements, plantes, équipements, persistance, configuration exportée |
| 10 | [Décisions et traçabilité](docs/10-decisions-tracabilite.md) | `Decision` / `Action`, cycle de vie, arbre des actions |
| 11 | [Agent de décision](docs/11-agent-decision.md) | Agent LLM qui explique et propose, outils, garde-fous |
| 12 | [Interface utilisateur et API](docs/12-interface-utilisateur.md) | FastAPI, écrans React, tests |
| 13 | [Vue jeu pixel art](docs/13-interface-jeu-pixel-art.md) | Serre animée, jardinier, mode construction |
| 14 | [Résultats phases 1 et 2](docs/14-resultats-phase1.md) | Analyse du classifieur et du détecteur |
| 15 | [Améliorations de la détection](docs/15-ameliorations-detection.md) | Plan de travail sur le pipeline deux étages |
| 16 | [Test système simulé](docs/16-test-systeme-simule.md) | Scénarios scriptés sans images (journée capteurs, mildiou et agent), attendus vérifiés, historique figé, journal de test et constats |
| 17 | [Analyse du système](docs/17-analyse-systeme.md) | État des lieux du logiciel : forces, limites par domaine, synthèse des risques |
| 18 | [Améliorations logicielles](docs/18-ameliorations-logicielles.md) | Plan d'améliorations réalisables sans matériel, par priorité et par lot (Q1–Q5) |
| 19 | [Notebooks d'analyse des datasets](docs/19-notebooks-analyse-datasets.md) | Spécification des notebooks 06–08 : statistiques du classifieur, du jeu YOLO et des séries capteurs |
| — | [Données sur Google Drive](docs/data-drive.md) | Archives des datasets, rclone, Colab, rapatriement des sorties |

## État actuel (17/10/2026)

- ✅ Données rangées (`data/plantvillage`, `data/ccmt`, `data/plantdoc`), taxonomie unifiée et **`data/index.parquet`** généré : 88 135 images, 16 espèces, 56 classes, splits groupés sans fuite (détail dans [02-donnees](docs/02-donnees.md)).
- ⚠️ GPU NVIDIA RTX 1000 Ada (6 Go) présent, mais aucun driver installé (`nvidia-smi`) : installer `nvidia-driver-595-open` puis `make cuda-torch` → voir [08-environnement](docs/08-environnement.md). État du poste : `make check-env`.
- ✅ Squelette du dépôt, `pyproject.toml` et **contrat MQTT** (`common/mqtt/`, testé) en place — cf. [01-architecture](docs/01-architecture.md).
- ✅ **Classifieur phase 1** écrit (dataset, augmentations + remplacement de fond, modèle multi-têtes, entraînement MLflow, évaluation cross-domain, Grad-CAM, export ONNX) et testé sur CPU — cf. [03-classifieur](docs/03-classifieur.md). **Notebooks Colab** (`notebooks/`, données servies par Google Drive) pour lancer les entraînements et les ablations A–E sur GPU ; reste à constituer `data/backgrounds/`.
- ✅ Données archivées sur **Google Drive** (`tools/get_datasets.sh`, rclone) — cf. [data-drive](docs/data-drive.md).
- ✅ **Edge** (doc 05) écrit et testé sur PC : bundle de modèles, calibration et scripts Hailo, service caméra (ONNX Runtime, mode sans broker), alertes vision lissées, apprentissage actif, systemd — cf. [05-edge-deploiement §7](docs/05-edge-deploiement.md#7-implémentation-et-test-sur-pc). HEF / HailoRT / picamera2 à valider sur le Pi.
- ✅ **Capteurs et contrôle** (doc 06) écrits et testés sur PC : contrat MQTT étendu (dont le topic `decision`), contrôleur (sécurité, règles, risque, prévision GRU), simulateur MQTT avec pannes injectables, firmware des 4 nœuds XIAO ESP32-C6 — cf. [06 §6](docs/06-capteurs-controle.md#6-implémentation-et-test-sur-pc). Firmware à compiler et flasher, GRU à entraîner.
- ✅ **Base de la serre et ingestion** (G1 + « en parallèle », docs 07/09) : schéma PostgreSQL/TimescaleDB (`backend/db/`), seed depuis `serre.yaml`, ingestion MQTT → base (`backend/ingestion/`), consommation journalière estimée (kWh, L, DLI, €), stack Docker TimescaleDB + Grafana avec dashboard « Serre » — cf. [09 §7](docs/09-modele-gestion-serre.md#7-persistance). Testé sur PC (SQLite, simulateur intégré) ; dashboard Grafana à vérifier sur la stack Docker.
- ✅ **Modèle de serre complet** (doc 09, hors UI) : contenants, capteurs déclarés, caméras et régions, contrôles de cohérence, intrants des pompes doseuses, export versionné de `serre.yaml` vers le Pi (`make config-export`) — cf. [09 §8](docs/09-modele-gestion-serre.md#8-configuration-exportée-vers-le-contrôleur).
- ✅ **Traçabilité des décisions** (G3, doc 10) : règles « classification → action » (`edge/controller/vision_rules.py`, `regles.yaml`), décisions proposées / validées / rejetées / expirées, table `action` confirmée par `etat/`, état des plantes, arbre des actions (`make arbre`), caméras simulées et panne `maladie:` — cf. [10 §8](docs/10-decisions-tracabilite.md#8-implémentation-et-test-sur-pc) ; fiche décision et vue arbre dans l'UI (G2).
- ✅ **Agent de décision** (G4, doc 11) : boucle Claude (`claude-sonnet-5-5` par défaut) et 12 outils (`backend/agent/`), propositions `niveau: agent` validées par `POST /api/decisions/{id}/valider`, garde-fous vérifiés avant création (durées, actionneurs, limites de sécurité, preuves existantes), consignes appliquées à la recette après validation, journal `agent_journal`, budgets, chat SSE `POST /api/agent/chat` et onglet Agent de l'UI ; 12 questions de référence (`make agent-eval`, Claude réel) — cf. [11 §7](docs/11-agent-decision.md#7-implémentation-et-test-sur-pc). Testé avec un LLM scripté ; pas encore joué avec Claude réel.
- ✅ **API et interface web** (G2, doc 12) : API REST complète sous `/api` (structure, plantes, équipements, publication de la configuration, mesures, tableau de bord, images, consommation, alertes, authentification optionnelle), relais `WS /ws/live`, SPA React + Vite (`frontend/`) : constructeur avec plan glisser-déposer et éditeur de régions, équipements, tableau de bord, consommation, journal et fiche décision, arbre des actions, agent ; serre simulée derrière l'API sans broker (`make api-sim`) — cf. [12 §7](docs/12-interface-utilisateur.md#7-implémentation-et-test-sur-pc). Testé par pytest, Vitest et Playwright ; Alembic à venir.
- ✅ **Vue jeu pixel art** (J1–J5, doc 13) : `/jeu` en Phaser 3, serre construite case par case depuis un inventaire, jardinier qui rejoue les événements réels, bulles de stats, rejeu 24 h / 7 j, démo hors ligne `/jeu?demo=1` ; sprites générés (planches 01 à 04 : jardinier et ses actions, 16 espèces) → atlas par `make sprites`, prompts des planches suivantes dans [`sprites-src/PROMPTS.md`](sprites-src/PROMPTS.md).
- 🔄 **Test système simulé** (T1, doc 16) : scénarios scriptés `sim --scenario journee|mildiou` (forçages, pannes, vision factice) rejoués au plus vite et vérifiés contre leurs attendus (`make scenario`, `tests/test_scenarios.py`), historique figé pour l'UI, la vue jeu (`/jeu?demo=mildiou`) et l'agent (`make scenario-figer`, `make api-historique`) ; premier passage fait, 5 constats sur le contrôleur et la consommation à traiter, parcours UI et agent avec Claude réel restants — cf. [16 §6](docs/16-test-systeme-simule.md#6-journal-de-test).
- 📋 **Analyse et qualité logicielle** (docs 17 et 18) : état des lieux complet (10 risques principaux, dont chauffage non borné sur sonde muette et bus MQTT sans authentification) et plan d'améliorations sans matériel en 5 lots, Q1 (sécurité et justesse) avant toute mise en serre — cf. [18 §11](docs/18-ameliorations-logicielles.md#11-ordre-proposé).
- ✅ **Notebooks d'analyse des datasets** (doc 19) écrits : `06_stats_classifieur` (déséquilibre, classes mono-source, écart de domaine, doublons), `07_stats_yolo` (boîtes : toutes de classe `feuille` aujourd'hui) et `08_stats_capteurs` (trous, profils journaliers, actionneurs), calculs testés dans `vision/datasets/stats.py` et `sim/stats.py`, rapports dans `reports/datasets/` ; à exécuter pour recouper les chiffres — cf. [19](docs/19-notebooks-analyse-datasets.md).

## Démarrage rapide

Disponible dès maintenant :
```bash
uv sync                                                # dépendances de base + dev
make setup                                             # poste complet (vision, notebook, backend, controle)
make check-env                                         # diagnostic : driver, torch/CUDA, extras, outils
make test                                              # tests (contrat MQTT, taxonomie, index…)
make lint                                              # ruff format + check
```

Classifieur (phase 1) :
```bash
uv sync --extra vision                                 # dépendances d'entraînement
uv run python -m vision.datasets.build_index           # index.parquet + splits
uv run python -m vision.train.train_classifier --config configs/clf_effnet_b0.yaml
uv run python -m vision.eval.cross_domain_eval --run <run_id>
uv run python -m vision.eval.gradcam --run <run_id>
uv run python -m vision.export.to_onnx --run <run_id>
make mlflow                                            # suivi des expériences (mlruns/mlflow.db)
```

Edge, sur PC sans Pi ni broker (doc 05 §7) :
```bash
uv sync --extra vision --extra detection --extra edge
uv run python -m vision.export.package --classifier <run_id> --version clf-effb0-v1
uv run python -m edge.camera_service --once --mqtt none     # images de data/plantdoc/test
uv run python -m edge.controller.vision_alerts --replay edge/archive
```

Contrôle et simulateur, sur PC sans broker (doc 06 §6) :
```bash
uv sync --extra controle
uv run python -m sim --mqtt none --avec-controleur --accel 0 --duree-h 2 --debut 2026-07-15T06:00
uv run python -m sim --mqtt none --avec-controleur --accel 0 --duree-h 3 --panne cuve_vide:z2@30
```

Base, ingestion et dashboard (doc 09 §7) :
```bash
uv sync --extra backend --extra controle
uv run python -m backend.ingestion --sim --duree-h 24 --debut 2026-07-15T00:00 --db sqlite:///serreia.db
uv run python -m backend.consumption --jour 2026-07-15 --db sqlite:///serreia.db
make stack-up && make db-init && make sim-demo         # TimescaleDB + Grafana (localhost:3000, admin / serreia)
make ingest                                            # ingestion du broker en continu
```

### Lancer l'interface (doc 12 §5 et §7)

Une fois : le Makefile appelle `python`, le venv doit donc être actif (sinon `make … PY="uv run python"`) ;
Node.js ≥ 20 pour le front.
```bash
source .venv/bin/activate
make front-install                                     # dépendances npm
```

**Interface + serre simulée** (sans Docker, broker ni Pi ; base SQLite) — le plus simple :
```bash
make api-sim                                           # terminal 1 : API + simulateur + contrôleur sur :8000
make front-dev                                         # terminal 2 : http://localhost:5173 (proxy vers :8000)

make api-sim SCENARIO=journee                          # un scénario scripté (doc 16) depuis son début, ×60
make api-sim SCENARIO=mildiou ACCEL=120                # … plus vite
make api-sim PANNE=maladie:z1-A1/tomate/maladie/mildiou@15   # serre libre + une panne (proposition à valider)
```
En un seul terminal : `make front-build` une fois, puis `make api-sim …` sert l'interface sur
http://localhost:8000. Vue jeu : `/jeu`.

**Interface sur un historique figé** (reproductible, lecture seule) :
```bash
make scenario-figer NOM=mildiou                        # data/scenarios/mildiou/ + JSON de la vue jeu
make api-historique NOM=mildiou                        # terminal 1, horloge arrêtée à la fin du scénario
make front-dev                                         # terminal 2 ; hors ligne sans API : /jeu?demo=mildiou
```

**Interface sur la vraie serre** (broker + TimescaleDB, extra `backend` : `psycopg`) :
```bash
uv sync --extra backend --extra controle               # ou pip install "psycopg[binary]"
make stack-up && make db-init                          # Docker : TimescaleDB, Grafana, mosquitto
make api                                               # terminal 1
make front-dev                                         # terminal 2
```

Tests du front : `make front-test e2e` (Vitest, parcours Playwright). Onglet Agent : `ANTHROPIC_API_KEY`
(sans clé, seul cet onglet est dégradé).

Dépannage :

| Symptôme | Cause, remède |
|---|---|
| `ModuleNotFoundError: No module named 'psycopg'` sur `make api` | `make api` vise PostgreSQL par défaut (`$SERREIA_DB`) : `uv sync --extra backend`, puis `make stack-up`. Ou utiliser `make api-sim` (SQLite) |
| `address already in use` sur `127.0.0.1:8000` | une API tourne déjà (autre terminal) : `ss -ltnp \| grep :8000` → `kill <pid>` ou Ctrl+C dans son terminal. Deux `make api-sim SCENARIO=…` du même nom se partagent aussi la base : n'en garder qu'un |
| `make: python: commande introuvable` ou module manquant | venv non actif : `source .venv/bin/activate` |
| l'interface (5173) ne montre rien | l'API n'est pas lancée : `make front-dev` envoie `/api` et `/ws` vers `:8000` |

### Scénarios simulés (doc 16)
```bash
make scenario NOM=journee                              # rejoué au plus vite, vérifié contre ses attendus
make scenario-figer NOM=mildiou                        # historique figé (SQLite, JSON de la vue jeu)
uv run pytest tests/test_scenarios.py                  # les deux scénarios + l'agent factice (~1 min 30)
make agent-eval HISTORIQUE=data/scenarios/mildiou      # agent avec Claude réel (tokens dépensés)
```

Notebooks (`notebooks/`, ouvrables dans Colab via leur badge) :

| Notebook | Rôle |
|---|---|
| `01_donnees.ipynb` | index, effectifs, exemples, aperçu des augmentations et du remplacement de fond |
| `02_entrainement.ipynb` | un run complet : entraînement, évaluation, Grad-CAM, ONNX |
| `03_evaluation.ipynb` | évaluation d'un run existant |
| `04_ablations.ipynb` | ablations A–E à la suite (reprise possible) → `reports/phase1.md` |
| `05_detection.ipynb` | jeu YOLO, entraînement du détecteur, pipeline deux étages (doc 04) |
| `06_stats_classifieur.ipynb` | statistiques de l'index : déséquilibre, couverture, splits, photométrie, doublons → `reports/datasets/classifieur/` |
| `07_stats_yolo.ipynb` | statistiques du jeu YOLO : effectifs, géométrie et qualité des boîtes → `reports/datasets/yolo/` |
| `08_stats_capteurs.ipynb` | séries capteurs et actionneurs d'un scénario, de `sim` ou d'une base → `reports/datasets/capteurs/` |

```bash
tools/get_datasets.sh check                            # état des jeux (data/ ↔ Google Drive)
tools/get_datasets.sh pull plantvillage                # récupérer un jeu depuis le Drive
make harvest                                           # rapatrier les sorties Colab (runs/, reports/, mlruns/colab/)
make notebooks                                         # régénérer notebooks/ (efface les sorties enregistrées)
```
