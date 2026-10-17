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
| 16 | [Test système simulé](docs/16-test-systeme-simule.md) | Scénarios sans images : journée capteurs, mildiou et agent, vus dans l'UI |
| — | [Données sur Google Drive](docs/data-drive.md) | Archives des datasets, rclone, Colab, rapatriement des sorties |

## État actuel (16/10/2026)

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
- 📝 **Test système simulé** (doc 16) : scénarios « journée capteurs » et « mildiou et agent » décrits, à implémenter et jouer après G2–G4 et J3 — cf. [16](docs/16-test-systeme-simule.md).

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

API et interface web (doc 12 §7 ; Node.js ≥ 20 pour le front) :
```bash
make front-install front-build                         # dépendances npm, build servi par l'API
make api-sim PANNE=maladie:z1-A1/tomate/maladie/mildiou@15   # API + serre simulée → http://127.0.0.1:8000
make front-dev                                         # développement : Vite sur :5173 (proxy vers :8000)
make front-test e2e                                    # Vitest, parcours Playwright
```

Notebooks (`notebooks/`, ouvrables dans Colab via leur badge) :

| Notebook | Rôle |
|---|---|
| `01_donnees.ipynb` | index, effectifs, exemples, aperçu des augmentations et du remplacement de fond |
| `02_entrainement.ipynb` | un run complet : entraînement, évaluation, Grad-CAM, ONNX |
| `03_evaluation.ipynb` | évaluation d'un run existant |
| `04_ablations.ipynb` | ablations A–E à la suite (reprise possible) → `reports/phase1.md` |

```bash
tools/get_datasets.sh check                            # état des jeux (data/ ↔ Google Drive)
tools/get_datasets.sh pull plantvillage                # récupérer un jeu depuis le Drive
make harvest                                           # rapatrier les sorties Colab (runs/, reports/, mlruns/colab/)
make notebooks                                         # régénérer notebooks/ (tools/notebooks/build.py)
```
