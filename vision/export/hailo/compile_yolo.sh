#!/usr/bin/env bash
# YOLOv8n ONNX -> HEF with NMS on the chip, from the Hailo Model Zoo config (docs/05 §2).
# Runs in the "Hailo AI SW Suite" Docker (hailomz installed), see README.md.
#
#   vision/export/hailo/compile_yolo.sh edge/models/<v>/yolo.onnx runs/export/calib_yolo hailo8l 3
#
# $2: folder of calibration images (python -m vision.export.calibration --model yolo
#     --n 512 --images-out runs/export/calib_yolo); $4: number of classes (feuille, plante, fruit).
set -euo pipefail

ONNX=${1:?yolo.onnx}
CALIB=${2:?dossier d'images de calibration}
ARCH=${3:-hailo8l}
NC=${4:-3}

OUT_DIR=$(dirname "$ONNX")
cd "$OUT_DIR"
hailomz compile yolov8n \
    --ckpt "$(basename "$ONNX")" \
    --hw-arch "$ARCH" \
    --calib-path "$CALIB" \
    --classes "$NC"
mv -f yolov8n.hef yolo.hef
echo "HEF : $OUT_DIR/yolo.hef ($ARCH)"
