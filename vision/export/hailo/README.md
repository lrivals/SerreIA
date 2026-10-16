# Compilation Hailo (docs/05 §2)

À lancer sur un **PC x86** dans le Docker « Hailo AI SW Suite » (Dataflow Compiler, Model Zoo,
HailoRT) — téléchargeable depuis le Hailo Developer Zone (compte gratuit). Pas besoin du Pi
ni de la carte : la compilation et l'émulation quantifiée tournent sur CPU.

```bash
# 1. Sur le PC (venv du projet) : bundle ONNX + calibration
python -m vision.export.package --classifier <run_id> --detector runs/<yolo>/best.pt --version clf-effb0-v1
python -m vision.export.calibration --model clf --n 1024
python -m vision.export.calibration --model yolo --n 512 --images-out runs/export/calib_yolo

# 2. Dans le Docker (dépôt monté sur /local/workspace/SerreIA)
cd /local/workspace/SerreIA
python vision/export/hailo/compile_clf.py --onnx edge/models/clf-effb0-v1/clf.onnx \
    --calib runs/export/calib_clf_224.npy --hw-arch hailo8l      # hailo8 pour l'AI HAT+ 26 TOPS
vision/export/hailo/compile_yolo.sh edge/models/clf-effb0-v1/yolo.onnx \
    "$PWD/runs/export/calib_yolo" hailo8l 3

# 3. Écart INT8 vs ONNX, toujours dans le Docker (pip install -e '.[vision,edge]' au besoin)
python -m vision.export.evaluate_backend --bundle edge/models/clf-effb0-v1 \
    --candidate har --har edge/models/clf-effb0-v1/clf.q.har     # critère < 2 pts
```

Puis ajouter `"hef": "clf.hef"` / `"hef": "yolo.hef"` dans `manifest.json` (fait par
`python -m vision.export.package --add-hef <dossier>`), copier le bundle sur le Pi
(`edge/deploy.sh`) et vérifier :

```bash
hailortcli benchmark edge/models/current/clf.hef     # latence, FPS
vcgencmd measure_temp                                 # température du SoC
python -m vision.export.evaluate_backend --bundle edge/models/current --candidate hailo
```

Points à surveiller :
- noms et ordre des sorties du HEF (affichés par `compile_clf.py`) : `order_outputs` les
  remet dans l'ordre espece / sante / classe par leur taille ;
- YOLO : la config `yolov8n` du Model Zoo suppose les nœuds de sortie d'Ultralytics 8.x ;
  si le parse échoue, passer `--end-node-names` (voir `hailomz compile --help`) ;
- opérateur non supporté au parse : changer de backbone pour un modèle du Model Zoo
  (risque listé dans docs/07).
