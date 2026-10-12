# 07 — Feuille de route

## Étapes

| Étape | Durée indicative | Contenu | Critère de validation |
|---|---|---|---|
| **S1 — Données et environnement** | 1 semaine | nettoyage de `data/`, téléchargement de PlantDoc, driver CUDA, `uv`, `taxonomy.yaml`, `build_index.py` | `index.parquet` généré, tests de non-fuite OK, effectifs conformes |
| **S2–S3 — Classifieur** | 2 semaines | modèle multi-têtes, augmentations, remplacement de fond, MLflow, ablations A–E | critères de sortie de [03 §6](03-classifieur.md#6-critères-de-sortie-de-la-phase-1), rapport `reports/phase1.md` |
| **S4 — Export edge** | 1 semaine | ONNX → HEF, benchmark sur le Pi 5 + Hailo | écart HEF/ONNX < 2 pts, latence mesurée |
| **S5–S7 — Détection** | 3 semaines | PlantDoc → YOLO, pseudo-labels (Grad-CAM + SAM 2), Label Studio, deux étages | mAP@0.5 « feuille » ≥ 0,6 ; pipeline de bout en bout sur des photos réelles |
| **En parallèle** | continu | simulateur MQTT, ingestion → TimescaleDB, dashboard Grafana | dashboard alimenté par le simulateur |
| **S8+ — Serre réelle** | — | premier nœud ESP32 (air), caméra fixe, `camera_service`, sécurités | 7 jours sans intervention, alertes cohérentes |
| **Ensuite** | — | nœud solution (pH/EC), PatchCore, suivi de croissance, apprentissage actif, prévision GRU | voir docs 04, 05, 06 |

## Premier lot de développement
1. ✅ `pyproject.toml` (uv), squelette du dépôt et contrat MQTT `common/mqtt/` + `tests/test_mqtt_contract.py`
2. ✅ `vision/datasets/taxonomy.yaml`
3. ✅ `vision/datasets/prepare.py`, `build_index.py` + `tests/test_index.py`, `test_taxonomy.py`, `test_near_duplicates.py`
4. ✅ `vision/datasets/dataset.py`, `augment.py`
5. ✅ `vision/models/multihead.py`
6. ✅ `vision/train/train_classifier.py` + `configs/clf_effnet_b0.yaml` (+ `configs/ablations/`)
7. ✅ `vision/eval/cross_domain_eval.py`, `gradcam.py` (+ `vision/export/to_onnx.py`) — code testé sur CPU ; entraînements réels en attente de `data/backgrounds/`
8. ✅ Notebooks Colab `notebooks/01–04` (générés par `tools/notebooks/build.py`) et données archivées sur Google Drive (`tools/get_datasets.sh`, [data-drive](data-drive.md))

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
