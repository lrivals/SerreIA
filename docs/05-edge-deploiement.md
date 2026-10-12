# 05 — Edge et déploiement (Raspberry Pi 5 + Hailo)

## 1. Matériel

| Élément | Choix | Remarque |
|---|---|---|
| Calcul | Raspberry Pi 5, 8 Go | |
| Accélérateur | Raspberry Pi AI Kit (Hailo-8L, 13 TOPS) ou AI HAT+ 26 TOPS (Hailo-8) | le 26 TOPS laisse de la marge pour YOLO + classifieur + PatchCore |
| Stockage | SSD NVMe (via HAT) ou USB | éviter la carte SD pour les écritures d'images |
| Caméras | Camera Module 3 (CSI, ×2 ports) + webcams USB si besoin | NoIR possible plus tard (NDVI) |
| Alimentation | 27 W officielle | |
| OS | Raspberry Pi OS 64 bits (Bookworm), `hailo-all` | |

## 2. Chaîne d'export — `vision/export/`

```
PyTorch (.pt) ──to_onnx.py──► ONNX (opset 17, entrée fixe 1×3×224×224)
     │                           │ onnxruntime : vérification de l'écart < 0,5 pt
     │                           ▼
     │                 Hailo Dataflow Compiler (sur PC x86, Docker « Hailo AI SW Suite »)
     │                   parse → optimize (quantification INT8, calibration) → compile
     │                           ▼
     │                         .hef ──► Pi 5 (HailoRT / hailo-apps)
```

- **Calibration INT8** : 512 à 1 024 images représentatives, *incluant des images de serre* dès que possible (sinon un mélange des splits `val`).
- Un modèle multi-têtes produit 3 sorties : vérifier leur nom et leur ordre dans le HEF.
- Pour YOLO : partir de la configuration du **Hailo Model Zoo** (`yolov8n`) avec post-processing NMS sur la puce.
- Critère : écart de précision **HEF vs ONNX < 2 points** sur `test` et `test_xdomain`.
- Benchmark sur le Pi : latence et FPS (`hailortcli benchmark`), température du SoC.

## 3. Service caméra — `edge/camera_service.py`

Boucle (service systemd) :
1. **Planification** : capture toutes les 10 min (paramétrable), plus des captures à la demande via `serre/<zone>/cmd/capture`.
2. **Éclairage maîtrisé** : si les LED horticoles sont colorées, publier `cmd/led` → blanc (ou couper) pendant 2 s, puis capturer. Cela améliore beaucoup la cohérence des images.
3. Pré-traitement : correction de la balance des blancs (mire grise fixe dans le champ), redimensionnement.
4. Inférence : YOLO → crops → classifieur → PatchCore (si disponible) → indicateurs de croissance.
5. Publication MQTT `serre/<zone>/vision/<camera>` (schéma en [01](01-architecture.md#schémas-json)).
6. Archivage : JPEG + JSON localement (tampon circulaire de 7 jours), puis upload asynchrone vers le serveur.

Configuration `edge/config.yaml` : caméras (id, zone, résolution, ROI par plante), période, seuils, chemins des HEF.

## 4. De la prédiction à l'alerte (dans `controller`)
- **Lissage temporel** : une plante n'est déclarée « anormale » que si `sante_conf > seuil` sur **N = 3 captures consécutives** (ou moyenne glissante). Cela supprime les faux positifs dus aux reflets ou aux ombres.
- **Fusion avec les capteurs** : par exemple, une détection de mildiou combinée à une humidité supérieure à 85 % pendant plus de 6 h élève le niveau d'alerte.
- Niveaux : `info` (journal), `attention` (dashboard), `critique` (notification).

## 5. Boucle d'apprentissage actif
```
captures ──► incertitude (entropie, conf < 0,6) ou anomalie élevée ──► file Label Studio
   ▲                                                                       │ annotation
   │                                                                       ▼
déploiement HEF ◄── export ◄── ré-entraînement (RTX) ◄── index.parquet (source = serre)
```
- Échantillonnage : 50 images par semaine maximum (incertaines, diversifiées par plante et par heure).
- Chaque nouveau modèle est **évalué sur un jeu de serre figé** avant déploiement, puis déployé uniquement s'il n'y a pas de régression.
- Versionnage du modèle dans les messages MQTT (`"modele": "clf-effb0-v3"`) et dans MLflow.
- C'est ainsi qu'on ajoute **fraise, salades et aromatiques** : nouvelles entrées de taxonomie, puis annotation, puis ré-entraînement.

## 6. Exploitation
- Services systemd : `mosquitto`, `camera_service`, `sensor_bridge`, `controller`, avec redémarrage automatique.
- Watchdog matériel du Pi activé.
- Logs : journald + envoi des erreurs au serveur.
- Mises à jour : `git pull` + `uv sync` + redémarrage des services ; HEF copiés dans `edge/models/` avec un lien symbolique `current`.
