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

## État actuel (12/10/2026)

- ✅ Datasets téléchargés dans `data/`, **mais deux dossiers sont mal nommés et un dataset manque** (détail dans [02-donnees](docs/02-donnees.md#1-état-réel-du-dossier-data)) :
  - `data/PlantVillage Dataset/` contient en réalité **ASL Alphabet** (langue des signes) → à supprimer ;
  - `data/PlantDoc Dataset/plantvillage dataset/` contient en réalité **PlantVillage** ;
  - **le vrai PlantDoc n'est pas encore téléchargé.**
- ⚠️ GPU NVIDIA RTX 1000 Ada (6 Go) présent, mais le driver ne répond pas (`nvidia-smi`) → voir [08-environnement](docs/08-environnement.md).
- ✅ Squelette du dépôt, `pyproject.toml` et **contrat MQTT** (`common/mqtt/`, testé) en place — cf. [01-architecture](docs/01-architecture.md).
- ⏳ Vision, edge, backend, simulateur et firmware : à écrire.

## Démarrage rapide (une fois le code écrit)

```bash
uv sync                                                # dépendances
uv run python -m vision.datasets.build_index           # index.parquet + splits
uv run python -m vision.train.train_classifier --config configs/clf_effnet_b0.yaml
uv run python -m vision.eval.cross_domain_eval --run <run_id>
uv run mlflow ui                                       # suivi des expériences
```
