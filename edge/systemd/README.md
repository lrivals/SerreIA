# Exploitation du Pi (docs/05 §6)

Services systemd, redémarrage automatique (`Restart=always`) et watchdog logiciel
(`WatchdogSec`, notifications `WATCHDOG=1` envoyées par les services) :

| Unité | Rôle |
|---|---|
| `mosquitto` | broker MQTT (paquet Debian) |
| `serreia-camera.service` | `python -m edge.camera_service` |
| `serreia-vision-alerts.service` | `python -m edge.controller.vision_alerts` |
| `sensor_bridge`, `controller` | à venir (docs/06) |

Installation (une fois, sur le Pi, utilisateur `serre`, dépôt dans `/home/serre/SerreIA`) :

```bash
sudo apt install mosquitto hailo-all python3-picamera2
uv venv --system-site-packages        # picamera2 et hailo_platform viennent d'apt
uv sync --extra edge
sudo cp edge/systemd/serreia-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mosquitto serreia-camera serreia-vision-alerts
```

Watchdog matériel du Pi 5 (redémarre la carte si le système se fige) :

```bash
# /etc/systemd/system.conf
RuntimeWatchdogSec=15
RebootWatchdogSec=2min
```
puis `sudo systemctl daemon-reexec`.

Journaux : `journalctl -u serreia-camera -f`. Les échecs répétés d'une caméra sont publiés en
alerte `warning` sur `serre/<zone>/alerte` (remontée des erreurs au serveur).

Mise à jour : `edge/deploy.sh [bundle]` (git pull, uv sync, bascule du modèle, redémarrage).
