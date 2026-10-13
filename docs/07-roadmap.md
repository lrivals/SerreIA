# 07 — Feuille de route

## Étapes

| Étape | Durée indicative | Contenu | Critère de validation |
|---|---|---|---|
| **S1 — Données et environnement** | 1 semaine | nettoyage de `data/`, téléchargement de PlantDoc, driver CUDA, `uv`, `taxonomy.yaml`, `build_index.py` | `index.parquet` généré, tests de non-fuite OK, effectifs conformes |
| **S2–S3 — Classifieur** | 2 semaines | modèle multi-têtes, augmentations, remplacement de fond, MLflow, ablations A–E | critères de sortie de [03 §6](03-classifieur.md#6-critères-de-sortie-de-la-phase-1), rapport `reports/phase1.md` |
| **S4 — Export edge** | 1 semaine | ONNX → HEF, benchmark sur le Pi 5 + Hailo | écart HEF/ONNX < 2 pts, latence mesurée |
| **S5–S7 — Détection** | 3 semaines | PlantDoc → YOLO, pseudo-labels (Grad-CAM + SAM 2), Label Studio, deux étages | mAP@0.5 « feuille » ≥ 0,6 ; pipeline de bout en bout sur des photos réelles |
| **En parallèle** | continu | simulateur MQTT, ingestion → TimescaleDB, dashboard Grafana | dashboard alimenté par le simulateur |
| **S8+ — Serre réelle** | — | premiers nœuds XIAO ESP32-C6 (air, sol), caméra fixe, `camera_service`, sécurités | 7 jours sans intervention, alertes cohérentes |
| **G1 — Modèle de serre et base** | 1 semaine | schéma PostgreSQL/TimescaleDB ([09](09-modele-gestion-serre.md)), ingestion MQTT → DB, calcul des consommations | simulateur ingéré, consommation journalière calculée |
| **G2 — API et constructeur de serre** | 2 semaines | FastAPI CRUD, front React + Vite : constructeur, équipements, tableau de bord ([12](12-interface-utilisateur.md)), export de configuration vers le Pi | serre complète saisie dans l'UI et chargée par le controller |
| **G3 — Traçabilité des décisions** | 2 semaines | `Decision` / `Action`, topic `decision` dans `common/mqtt/`, journal, fiche décision, arbre des actions ([10](10-decisions-tracabilite.md)) | une décision du simulateur (vision + capteurs) visible dans l'UI avec ses preuves et ses actions |
| **G4 — Agent** | 1–2 semaines | boucle Claude + outils, propositions validables, garde-fous ([11](11-agent-decision.md)) | jeu de questions de référence réussi, aucune proposition hors limites |
| **J1–J5 — Vue jeu pixel art** | 3–5 semaines | serre construite et animée en pixel art, jardinier piloté par les événements réels, stats en bulles ([13](13-interface-jeu-pixel-art.md)) | scénario démo mildiou joué de bout en bout dans la vue jeu |
| **Ensuite** | — | nœud solution (pH/EC), PatchCore, suivi de croissance, apprentissage actif, prévision GRU | voir docs 04, 05, 06 |

## Premier lot de développement
1. ✅ `pyproject.toml` (uv), squelette du dépôt et contrat MQTT `common/mqtt/` + `tests/test_mqtt_contract.py`
2. ✅ `vision/datasets/taxonomy.yaml`
3. ✅ `vision/datasets/prepare.py`, `build_index.py` + `tests/test_index.py`, `test_taxonomy.py`, `test_near_duplicates.py`
4. ✅ `vision/datasets/dataset.py`, `augment.py`
5. ✅ `vision/models/multihead.py`
6. ✅ `vision/train/train_classifier.py` + `configs/clf_effnet_b0.yaml` (+ `configs/ablations/`)
7. ✅ `vision/eval/cross_domain_eval.py`, `gradcam.py` (+ `vision/export/to_onnx.py`) — entraînements réels faits (run principal + ablations A–E, analyse [14](14-resultats-phase1.md)) ; remplacement de fond encore à tester faute de `data/backgrounds/`
8. ✅ Notebooks Colab `notebooks/01–04` (générés par `tools/notebooks/build.py`) et données archivées sur Google Drive (`tools/get_datasets.sh`, [data-drive](data-drive.md))

Les étapes G1–G4 peuvent démarrer en parallèle de la vision : elles ne dépendent que du contrat MQTT et du simulateur.

## Risques et parades

| Risque | Impact | Parade |
|---|---|---|
| Écart de domaine labo → serre | modèle inutilisable en réel | remplacement de fond, test PlantDoc, images de serre au plus tôt, apprentissage actif |
| Taxonomie incohérente entre datasets | métriques faussées | règle « fusion seulement si sûre », classes `ambigu`, revue manuelle |
| Fuite train/test (quasi-doublons) | scores surestimés | splits groupés par pHash + dHash, CCMT Raw uniquement, tests automatiques |
| Opérateurs non supportés par Hailo | blocage du déploiement | export test dès le début de S2, backbones du Model Zoo |
| VRAM 6 Go | entraînement lent | AMP, batch 64 à 224 px, gradient accumulation si besoin |
| Faux positifs d'alerte | perte de confiance | lissage temporel, éclairage maîtrisé à la capture, seuils calibrés |
| Panne électronique ou pompe bloquée | dégâts matériels ou végétaux | sécurités dans le firmware, durées max, cuve vide, mode dégradé |
| Licence AGPL d'Ultralytics | contrainte en cas de diffusion | accepté pour un projet personnel ; alternative possible (RT-DETR, YOLOX sous Apache 2.0) |
| Agent LLM qui propose une action inadaptée | dégâts végétaux, perte de confiance | l'agent ne fait que proposer ; validation humaine, contrôle des limites dans l'outil puis `safety.py` |
| Journal de décisions illisible (trop de routines) | traçabilité inutilisable | agrégation des routines par cycle, filtres, arbre replié par défaut |
