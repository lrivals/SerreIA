#!/usr/bin/env bash
# Mise à jour du Pi (docs/05 §6) : code, dépendances, modèle, redémarrage des services.
#
#   edge/deploy.sh                          # code seulement
#   edge/deploy.sh /chemin/clf-effb0-v3     # + nouveau bundle (dossier avec manifest.json, HEF)
#
# Le bundle est copié dans edge/models/<version>, puis `current` bascule dessus. Avant :
# porte anti-régression sur le jeu de serre figé (vision.export.evaluate_backend, docs/05 §5).
set -euo pipefail

cd "$(dirname "$0")/.."
git pull --ff-only
uv sync --extra edge

if [[ $# -ge 1 ]]; then
    src=${1%/}
    version=$(basename "$src")
    [[ -f "$src/manifest.json" ]] || { echo "pas de manifest.json dans $src" >&2; exit 1; }
    mkdir -p edge/models
    rsync -a --delete "$src/" "edge/models/$version/"
    .venv/bin/python -m vision.export.package --set-current "$version"
fi

sudo systemctl restart serreia-camera serreia-vision-alerts
systemctl --no-pager --lines=0 status serreia-camera serreia-vision-alerts
