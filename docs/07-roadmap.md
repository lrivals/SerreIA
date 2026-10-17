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
| **G2 — API et constructeur de serre** | 2 semaines | FastAPI CRUD, front React + Vite : constructeur, équipements, tableau de bord ([12](12-interface-utilisateur.md)), export de configuration vers le Pi (côté backend déjà fait : `backend/config/export.py`, [09 §8](09-modele-gestion-serre.md#8-configuration-exportée-vers-le-contrôleur)) | serre complète saisie dans l'UI et chargée par le controller |
| **G3 — Traçabilité des décisions** | 2 semaines | `Decision` / `Action`, topic `decision` dans `common/mqtt/`, journal, fiche décision, arbre des actions ([10](10-decisions-tracabilite.md)) | une décision du simulateur (vision + capteurs) visible dans l'UI avec ses preuves et ses actions |
| **G4 — Agent** | 1–2 semaines | boucle Claude + outils, propositions validables, garde-fous ([11](11-agent-decision.md)) ; côté serveur fait ([11 §7](11-agent-decision.md#7-implémentation-et-test-sur-pc)), onglet UI avec G2 | jeu de questions de référence réussi, aucune proposition hors limites |
| **J1–J5 — Vue jeu pixel art** | 3–5 semaines | serre construite et animée en pixel art, jardinier piloté par les événements réels, stats en bulles ([13](13-interface-jeu-pixel-art.md)) ; ✅ fait avec les sprites de `planche_01` à `planche_04` : actions du jardinier, 16 espèces ([13 §11](13-interface-jeu-pixel-art.md#11-implémentation)) ; planches 05 à 10 à générer ([prompts](../sprites-src/PROMPTS.md)) | scénario démo mildiou joué de bout en bout dans la vue jeu |
| **T1 — Test système simulé** | 1 semaine | scénarios rejoués par le simulateur, sans images : « journée capteurs » et « mildiou et agent », vus dans l'UI et la vue jeu ([16](16-test-systeme-simule.md)) ; 🔄 outillage fait (`sim --scenario`, attendus, historique figé), mode rapide vert, 5 constats ([16 §6](16-test-systeme-simule.md#6-journal-de-test)) ; restent parcours UI et agent avec Claude réel | `tests/test_scenarios.py` vert, dialogues de référence réussis, journal de test rempli |
| **Q1–Q5 — Qualité logicielle** | 6–10 semaines | analyse [17](17-analyse-systeme.md), plan [18](18-ameliorations-logicielles.md) : sécurité du contrôleur (chauffage borné, état persistant), CI, ingestion et API fiabilisées, Alembic et Timescale, agent, vision (règle de décision unique, seuils hors domaine), front | Q1 avant la serre réelle, Q2 avant les 7 jours sans intervention ([18 §11](18-ameliorations-logicielles.md#11-ordre-proposé)) |
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
9. ✅ Phase 2 ([04](04-detection-yolo.md)) : `vision/labeling/` (jeu `data/yolo/`, pseudo-labels Grad-CAM + SAM 2, Label Studio), `vision/train/train_yolo.py` + `configs/yolo_v8n.yaml`, `vision/eval/two_stage.py`, `vision/anomaly/patchcore.py`, `vision/growth/`, notebook `05_detection` ; extra `detection` (ultralytics, sam2, scipy). Détecteur entraîné (run `a604f044`, YOLOv8n : mAP@0.5 val 0,888, test 0,956) et deux étages évalués sur PlantDoc TEST (42 % de faux positifs sur images saines), analyse [14](14-resultats-phase1.md) §8, plan d'amélioration [15](15-ameliorations-detection.md) ; pipeline sur photos réelles de la serre encore à évaluer.
10. ✅ Edge ([05](05-edge-deploiement.md)) côté code : bundle de modèles (`vision/export/package.py`), calibration INT8, scripts Hailo DFC, comparaison de backends, runtime `edge/vision/` (ONNX Runtime / HailoRT), `edge/camera_service.py`, alertes vision lissées (`edge/controller/vision_alerts.py`), apprentissage actif, systemd. Testé sur PC (ONNX, sans broker) ; HEF, HailoRT et picamera2 à valider sur le Pi.

11. ✅ Capteurs et contrôle ([06](06-capteurs-controle.md)) côté code : contrat MQTT étendu (`pression`, `presence`, `humidite_sol`, `pompe_nutri_a/b`, topic `decision` minimal), contrôleur `edge/controller/` (sécurité, règles, risque mildiou, prévision GRU → ONNX, décisions tracées), simulateur `sim/` (météo, modèle de zone, nœuds émulés, pannes), firmware `firmware/` (4 nœuds, logique pure testée). Testé sur PC (simulateur + contrôleur sur bus en mémoire) ; firmware à compiler et flasher, GRU à entraîner.
12. ✅ G1 + « En parallèle » ([09 §7](09-modele-gestion-serre.md#7-persistance)) : schéma PostgreSQL/TimescaleDB (`backend/db/`), seed depuis `serre.yaml`, ingestion MQTT → base (`backend/ingestion/`), consommation journalière (`backend/consumption.py` : kWh, L, DLI LED / naturel, coût), stack Docker TimescaleDB + Grafana + mosquitto et dashboard « Serre » provisionné. Critère G1 validé sur PC (`tests/test_ingestion_sim.py` : simulateur + contrôleur ingérés, consommation calculée, SQLite) ; à vérifier sur la stack Docker : hypertables (`SERREIA_TEST_PG`) et dashboard alimenté par le simulateur (`make sim-demo`).
13. ✅ Modèle de serre complet ([09](09-modele-gestion-serre.md)) hors UI : contenants, capteurs déclarés, caméras et régions dans `serre.yaml` et en base, contrôles de cohérence (`edge/controller/coherence.py`), espèces hors taxonomie sans décision vision automatique, intrants des pompes doseuses (mL), export versionné de la configuration vers le Pi (`backend/config/export.py`, `make config-export`). API et constructeur faits avec G2 (item 15) ; reste Alembic.
14. ✅ G3 hors UI ([10](10-decisions-tracabilite.md)) : `Decision` avec `ordres` et `expire`, règles « classification → action » (`edge/controller/vision_rules.py`, `regles.yaml`), cycle de vie proposée / validée / rejetée / expirée dans le contrôleur, table `action` dérivée et confirmée par `etat/`, état des plantes appliqué par le serveur, arbre des actions (`backend/traceability.py`, `make arbre`), API FastAPI minimale (`backend/api/`, `make api`), caméras simulées et panne `maladie:`. Critère G3 validé par l'API (`tests/test_traceability_sim.py` : décision mildiou du simulateur avec preuves vision + capteurs et actions confirmées, isolement validé puis exécuté) ; fiche décision et vue arbre React faites avec G2 (item 15).

15. ✅ G2 ([12](12-interface-utilisateur.md)) : API REST complète sous `/api` (structure, plantes, équipements, configuration cohérence / diff / publication, mesures, tableau de bord, vision et images, consommation, alertes, authentification optionnelle), relais `WS /ws/live`, SPA React + Vite (`frontend/` : constructeur avec plan glisser-déposer et éditeur de régions, équipements, tableau de bord, consommation, journal et fiche décision, arbre des actions, agent en streaming), serre simulée derrière l'API (`make api-sim`). Testé sur PC : pytest, Vitest, parcours Playwright (`make e2e`) ; critère G2 « chargée par le controller » à vérifier sur le Pi (publication `--rsync`).

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
