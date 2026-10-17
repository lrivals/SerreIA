# 01 — Architecture

## 1. Vue d'ensemble

```
                    ┌─────────────────────── SERRE ───────────────────────┐
                    │                                                     │
  [Nœud air]     ───┤  SHT41 (T/HR), BMP280 (pression), GY-302 (lux),     │
                    │  SCD41 (CO₂), HLK-LD2450 (radar de présence)        │
  [Nœud sol]     ───┤  sondes capacitives d'humidité du sol               │
  [Nœud cuve]    ───┤  pH, EC, DS18B20 (T° eau), niveau cuve              │
  [Nœud action]  ───┤  relais / MOSFET : pompes, ventilos, LED (PWM)      │
        │  Wi-Fi    │  (tous les nœuds : Seeed XIAO ESP32-C6)             │
        ▼  MQTT     │                                                     │
  ┌──────────────────────────────┐        caméras CSI / USB               │
  │ Raspberry Pi 5 + Hailo-8L    │◄───────────────────────────────────────┤
  │  • mosquitto (broker)        │                                        │
  │  • camera_service (vision)   │                                        │
  │  • controller (règles/ML)    │                                        │
  │  • vision_alerts (lissage)   │                                        │
  └──────────────┬───────────────┘                                        │
                 │ MQTT (bridge) + upload images                          │
                 ▼                                                        │
  ┌──────────────────────────────────────────────┐
  │ Serveur / PC (RTX 1000 Ada)                  │
  │  • TimescaleDB (séries) + stockage images    │
  │  • API FastAPI + dashboard (Grafana)         │
  │  • interface web React (serre, décisions)    │
  │  • agent conversationnel (Claude, conseil)   │
  │  • Label Studio (annotation)                 │
  │  • entraînement / ré-entraînement + MLflow   │
  └──────────────────────────────────────────────┘
```

### Principes
1. **Le Pi est autonome** : si le serveur tombe, la serre continue de tourner (contrôle et vision en local). Le serveur ne sert qu'à l'historique, au tableau de bord et à l'entraînement.
2. **La sécurité ne dépend jamais d'un modèle ML** : les limites dures (température max, temps max de pompe, cuve vide) sont appliquées dans le firmware ESP32 **et** dans le contrôleur.
3. **MQTT est le seul contrat entre les briques** : chaque brique peut être remplacée par un simulateur.

## 2. Contrat MQTT

### Topics
| Topic | Émetteur | QoS | Retain | Description |
|---|---|---|---|---|
| `serre/<zone>/capteur/<type>` | ESP32 / simulateur | 0 | non | mesure brute |
| `serre/<zone>/vision/<camera_id>` | camera_service | 1 | non | résultat d'inférence |
| `serre/<zone>/alerte` | controller | 1 | non | alerte consolidée |
| `serre/<zone>/cmd/<actionneur>` | controller / dashboard | 1 | non | commande |
| `serre/<zone>/cmd/capture` | controller / dashboard | 1 | non | capture d'image à la demande ([05 §3](05-edge-deploiement.md#3-service-caméra--edgecamera_servicepy)) |
| `serre/<zone>/etat/<actionneur>` | ESP32 | 1 | oui | état réel de l'actionneur |
| `serre/<noeud>/status` | ESP32 (LWT) | 1 | oui | `online` / `offline` |
| `serre/<zone>/decision` | controller / backend | 1 | non | décision et ses preuves, publiée avant les commandes — cf. [10 §2](10-decisions-tracabilite.md#2-enregistrement-decision) ; le backend publie les décisions validées (`validee`), que le contrôleur exécute via `safety.py` ([10 §4](10-decisions-tracabilite.md#4-cycle-de-vie)) |

`<zone>` : `z1`, `z2`… ; `<type>` : `temperature`, `humidite`, `co2`, `lux`, `ph`, `ec`, `temp_eau`, `niveau_cuve`, `pression` (hPa, BMP280), `presence` (nombre de cibles 0–3, HLK-LD2450), `humidite_sol` (%, sondes capacitives, avec `emplacement`). Plages physiques et unités : `common/mqtt/ranges.py`.
`<actionneur>` : `pompe_nutri`, `pompe_ph_down`, `pompe_nutri_a`, `pompe_nutri_b`, `ventilo`, `led`, `brumisateur`, `chauffage`.

### Schémas JSON

**Mesure capteur**
```json
{ "ts": "2026-10-12T14:03:00Z", "noeud": "esp32-01", "valeur": 23.4, "unite": "°C", "qualite": "ok" }
```
`qualite` ∈ `ok | suspect | erreur` (le firmware marque les valeurs hors plage physique). Sondes de sol : champ optionnel `"emplacement": "z1-A1"`.

**Résultat vision**
```json
{
  "ts": "2026-10-12T14:00:00Z",
  "camera": "cam-z1-a",
  "image_id": "z1-a-20261012T140000",
  "modele": "clf-effb0-v3",
  "detections": [
    {
      "bbox": [0.12, 0.30, 0.25, 0.22],
      "espece": "tomate", "espece_conf": 0.97,
      "sante": "anormal", "sante_conf": 0.88,
      "classe": "tomate/maladie/septoriose", "classe_conf": 0.74
    }
  ],
  "score_anomalie": 0.31,
  "surface_verte_px": 184233
}
```
En phase 1 (classifieur seul), `detections` contient un seul élément avec `bbox: null` (image entière ou tuile).

**Commande**
```json
{ "ts": "...", "action": "on", "duree_s": 30, "source": "controller", "raison": "dec-20261012-1403-z2-001 | pH 6.9 > consigne 6.2" }
```
`raison` : `"<id de décision> | <texte court>"` quand la commande vient d'une décision (contrôleur), texte libre sinon.
`action` ∈ `on | off | pwm` (avec `"valeur": 0-100`). `duree_s` est **obligatoire** pour les pompes : l'ESP32 coupe d'office à l'échéance.

**Capture à la demande** (`cmd/capture`) : `camera` absent ou `null` = toutes les caméras de la zone.
```json
{ "ts": "...", "source": "dashboard", "camera": "cam-z1-a" }
```

**Alerte**, **état d'actionneur**, **status**
```json
{ "ts": "...", "niveau": "warning", "message": "pH hors plage", "source": "controller" }
{ "ts": "...", "action": "pwm", "valeur": 60 }
```
`niveau` ∈ `info | warning | critique`. Le payload de `status` est la chaîne brute `online` ou `offline`.

Implémentation de référence : [`common/mqtt/`](../common/mqtt/) (`parse_topic`, `encode`, `decode`), testée par `tests/test_mqtt_contract.py`.

## 3. Organisation du dépôt

```
SerreIA/
├── README.md
├── docs/                      # cette documentation
├── data/                      # datasets bruts (non versionné)
│   ├── plantvillage/ ccmt/ plantdoc/   # rangés par vision.datasets.prepare
│   ├── index.parquet          # généré par build_index
│   └── yolo/                  # jeu de détection, généré par build_yolo_dataset (doc 04)
├── configs/                   # YAML d'entraînement / d'export
├── common/
│   └── mqtt/                  # contrat MQTT partagé : topics.py, schemas.py (pydantic), ranges.py
├── vision/
│   ├── datasets/              # taxonomy.yaml/.py, prepare.py, near_duplicates.py, build_index.py, dataset.py, augment.py
│   ├── models/                # multihead.py
│   ├── train/                 # train_classifier.py, train_yolo.py
│   ├── eval/                  # cross_domain_eval.py, gradcam.py, ablation_report.py, two_stage.py
│   ├── labeling/              # yolo_format.py, build_yolo_dataset.py, pseudo_labels.py (Grad-CAM + SAM 2), label_studio.py, active_learning.py
│   ├── anomaly/               # patchcore.py (anomalies non vues, doc 04 §4)
│   ├── growth/                # canopy.py, curve.py (suivi de croissance, doc 04 §5)
│   └── export/                # to_onnx.py, yolo_onnx.py, calibration.py, package.py, evaluate_backend.py, hailo/ (scripts DFC)
├── edge/                      # services Raspberry Pi (doc 05)
│   ├── camera_service.py      # + cameras.py, archive.py, publisher.py, config.py / config.yaml
│   ├── vision/                # backends ONNX / Hailo, détecteur, classifieur, pipeline (sans torch)
│   ├── models/                # bundles de modèles + lien current (non versionné)
│   ├── controller/            # contrôleur (doc 06) : service.py, safety.py, rules.py, risk.py, forecast.py,
│   │                          #   serre.yaml, recettes.yaml ; vision_alerts.py (doc 05)
│   ├── systemd/               # unités de service, watchdog
│   └── deploy.sh              # mise à jour du Pi
├── backend/                   # db/ (schéma, seed), ingestion/ (MQTT → DB), consumption.py,
│                              #   traceability.py, api/ (FastAPI, routes /api, doc 12), live/ (MQTT → WebSocket),
│                              #   agent/ (Claude, doc 11), config/ (export serre.yaml), docker-compose.yml + grafana/
├── frontend/                  # interface React + Vite (doc 12) : src/api, pages, components, live ; e2e/ (Playwright)
│                              #   src/game/ : vue jeu pixel art (Phaser, doc 13) ; public/sprites/ : atlas généré
├── sprites-src/               # planches pixel art brutes et découpées, manifeste sprites.json, PROMPTS.md (doc 13 §2)
├── firmware/                  # ESP32-C6 (PlatformIO) : un env par nœud, lib/serre_logic testée sur PC
├── sim/                       # simulateur : météo, modèle de zone, nœuds émulés, pannes (doc 06 §5)
├── tests/                     # test_mqtt_contract.py, …
└── pyproject.toml
```

## 4. Flux de données vision (cible)

```
caméra ──capture toutes les 10 min──► camera_service (Pi)
   │                                      ├─ YOLO (Hailo) : feuilles / plantes
   │                                      ├─ classifieur (Hailo) sur chaque crop
   │                                      ├─ score d'anomalie + surface verte
   │                                      └─ publish serre/z1/vision/cam-z1-a
   └──── image JPEG ──► serveur (archive) ──► file Label Studio si conf < seuil
```

## 5. Gestion de la serre, décisions et interface

La description de la serre physique, la traçabilité des décisions, l'agent conversationnel et l'interface web font l'objet de documents dédiés :
- [09 — Modèle de gestion de serre](09-modele-gestion-serre.md) : zones, emplacements, plantes, contenants, mode de culture, équipements, consommations, recettes ;
- [10 — Décisions et arbre des actions](10-decisions-tracabilite.md) : preuves vision + capteurs de chaque décision, routines vs actions exceptionnelles ;
- [11 — Agent de décision](11-agent-decision.md) : LLM qui explique et propose, le contrôleur reste seul décideur automatique ;
- [12 — Interface utilisateur et API](12-interface-utilisateur.md) : écrans, API REST/WebSocket, organisation `backend/` et `frontend/`.
