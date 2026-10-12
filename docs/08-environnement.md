# 08 — Environnement de développement

## 1. Poste d'entraînement (PC actuel)
- CPU : 22 threads ; RAM : 62 Go ; disque : ≈ 1,2 To libres
- GPU : **NVIDIA RTX 1000 Ada Laptop (6 Go)**, plus un iGPU Intel Arc
- Python 3.12

### Driver NVIDIA (à faire en premier)
`nvidia-smi` ne répond pas actuellement : le driver propriétaire n'est pas chargé.
```bash
ubuntu-drivers devices                 # driver recommandé
sudo ubuntu-drivers install            # ou : sudo apt install nvidia-driver-<version>
sudo reboot
nvidia-smi                             # doit afficher la RTX 1000 Ada
```
Secure Boot actif : enregistrer la clé MOK proposée pendant l'installation.
Pas besoin d'installer CUDA Toolkit séparément : les wheels PyTorch embarquent le runtime CUDA.

## 2. Gestion du projet Python avec `uv`
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv init --python 3.12
uv add torch torchvision --index https://download.pytorch.org/whl/cu124
uv add timm albumentations opencv-python-headless pandas pyarrow imagehash scikit-learn \
       mlflow pyyaml tqdm grad-cam onnx onnxruntime matplotlib
uv add ultralytics anomalib                    # phase 2
uv add paho-mqtt fastapi uvicorn psycopg       # edge / backend
uv add --dev pytest ruff
uv run python -c "import torch; print(torch.cuda.is_available())"
```

## 3. Outils annexes
| Outil | Usage | Installation |
|---|---|---|
| MLflow | suivi des expériences | `uv run mlflow ui` (stockage local `mlruns/`) |
| Label Studio | annotation | `docker run -p 8080:8080 heartexlabs/label-studio` |
| Hailo AI SW Suite | compilation HEF (x86 uniquement) | Docker, compte développeur Hailo |
| Mosquitto | broker MQTT | `sudo apt install mosquitto` |
| TimescaleDB + Grafana | séries temporelles et dashboard | `docker compose` (dans `backend/`) |
| PlatformIO | firmware ESP32 | extension VS Code |

## 4. Conventions
- **Langue** : code et identifiants en anglais ; documentation et noms de classes de la taxonomie en français.
- **Style** : `ruff` (format + lint) ; type hints ; fonctions courtes.
- **Configs** : tout hyperparamètre dans un YAML de `configs/`, jamais codé en dur.
- **Reproductibilité** : seed fixée ; chaque run MLflow enregistre la config, le commit git, la version de la taxonomie et le hash de `index.parquet`.
- **Données** : `data/`, `mlruns/` et les poids (`*.pt`, `*.onnx`, `*.hef`) sont exclus de git (`.gitignore`).
- **Données téléchargées** : à traiter comme non fiables (aucun script exécuté depuis ces dossiers).
- **Tests** : `uv run pytest`, au minimum sur l'index (non-fuite, effectifs), la taxonomie (tous les dossiers mappés) et le format des messages MQTT.
- **Git** : `git init` à la racine ; branches par fonctionnalité (`feat/build-index`, …).
