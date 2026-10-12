# 01 — Architecture

## 1. Vue d'ensemble

```
                    ┌─────────────────────── SERRE ───────────────────────┐
                    │                                                     │
  [Nœud ESP32 #1]───┤  SHT45 (T/HR), SCD41 (CO₂), BH1750 (lux)            │
  [Nœud ESP32 #2]───┤  pH, EC, DS18B20 (T° eau), niveau cuve              │
  [Nœud ESP32 #3]───┤  relais / MOSFET : pompes, ventilos, LED (PWM)      │
        │  Wi-Fi    │                                                     │
        ▼  MQTT     │                                                     │
  ┌──────────────────────────────┐        caméras CSI / USB               │
  │ Raspberry Pi 5 + Hailo-8L    │◄───────────────────────────────────────┤
  │  • mosquitto (broker)        │                                        │
  │  • camera_service (vision)   │                                        │
  │  • controller (règles/ML)    │                                        │
  │  • sensor_bridge (validation)│                                        │
  └──────────────┬───────────────┘                                        │
                 │ MQTT (bridge) + upload images                          │
                 ▼                                                        │
  ┌──────────────────────────────────────────────┐
  │ Serveur / PC (RTX 1000 Ada)                  │
  │  • TimescaleDB (séries) + stockage images    │
  │  • API FastAPI + dashboard (Grafana)         │
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
| `serre/<zone>/etat/<actionneur>` | ESP32 | 1 | oui | état réel de l'actionneur |
| `serre/<noeud>/status` | ESP32 (LWT) | 1 | oui | `online` / `offline` |

`<zone>` : `z1`, `z2`… ; `<type>` : `temperature`, `humidite`, `co2`, `lux`, `ph`, `ec`, `temp_eau`, `niveau_cuve`.
`<actionneur>` : `pompe_nutri`, `pompe_ph_down`, `ventilo`, `led`, `brumisateur`, `chauffage`.

### Schémas JSON

**Mesure capteur**
```json
{ "ts": "2026-10-12T14:03:00Z", "noeud": "esp32-01", "valeur": 23.4, "unite": "°C", "qualite": "ok" }
```
`qualite` ∈ `ok | suspect | erreur` (le firmware marque les valeurs hors plage physique).

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
{ "ts": "...", "action": "on", "duree_s": 30, "source": "controller", "raison": "pH 6.9 > consigne 6.2" }
```
`action` ∈ `on | off | pwm` (avec `"valeur": 0-100`). `duree_s` est **obligatoire** pour les pompes : l'ESP32 coupe d'office à l'échéance.

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
│   └── index.parquet          # généré par build_index
├── configs/                   # YAML d'entraînement / d'export
├── common/
│   └── mqtt/                  # contrat MQTT partagé : topics.py, schemas.py (pydantic)
├── vision/
│   ├── datasets/              # taxonomy.yaml/.py, prepare.py, near_duplicates.py, build_index.py, dataset.py, augment.py
│   ├── models/                # multihead.py
│   ├── train/                 # train_classifier.py, train_yolo.py
│   ├── eval/                  # cross_domain_eval.py, gradcam.py, report.py
│   ├── labeling/              # pseudo_labels.py (Grad-CAM + SAM), export Label Studio
│   └── export/                # to_onnx.py, hailo/ (scripts DFC)
├── edge/                      # services Raspberry Pi
│   ├── camera_service.py
│   ├── sensor_bridge.py
│   ├── controller/            # rules.py, safety.py, forecast.py
│   └── systemd/               # unités de service
├── backend/                   # FastAPI, schéma DB, ingestion MQTT → DB
├── firmware/                  # ESP32 (PlatformIO)
├── sim/                       # simulateur de capteurs / serre
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
