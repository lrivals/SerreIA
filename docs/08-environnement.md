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
Le `pyproject.toml` existe déjà. Les dépendances sont réparties en groupes :

| Groupe | Contenu | Installation |
|---|---|---|
| base | `pydantic`, `paho-mqtt` (contrat MQTT) | `uv sync` |
| `vision` | torch, torchvision, timm, albumentations, OpenCV, pandas, pyarrow, imagehash, scikit-learn, MLflow, grad-cam, ONNX… | `uv sync --extra vision` |
| `notebook` | ipykernel, nbclient, nbformat, ipywidgets (notebooks en local) | `uv sync --extra notebook` |
| `backend` | FastAPI, uvicorn, psycopg | `uv sync --extra backend` |
| `dev` | pytest, ruff | inclus par défaut dans `uv sync` |

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync                                        # base + dev
uv sync --extra vision                         # poste d'entraînement
uv run pytest                                  # tests
uv run ruff format . && uv run ruff check .    # style
uv run python -c "import torch; print(torch.cuda.is_available())"
```
Le `.venv` actuel contient **torch CPU** : une fois le driver installé, réinstaller torch/torchvision depuis l'index CUDA. Pour une version CUDA précise de PyTorch, ajouter l'index `https://download.pytorch.org/whl/cu124` dans `[tool.uv]`.
Phase 2 : `uv add ultralytics anomalib`.

**Sans uv** (solution de repli, utilisée tant que uv n'est pas installé) :
```bash
python3 -m venv .venv && .venv/bin/pip install -e . pytest ruff
.venv/bin/pip install pandas pyarrow imagehash scikit-learn pyyaml tqdm pillow  # données (doc 02), sans torch
# classifieur (doc 03) : torch CPU tant que le driver NVIDIA ne répond pas
.venv/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install -e '.[vision,notebook]'
.venv/bin/pytest -q
```

## 3. Outils annexes
| Outil | Usage | Installation |
|---|---|---|
| MLflow | suivi des expériences | `uv run mlflow ui --backend-store-uri sqlite:///mlruns/mlflow.db` (SQLite local `mlruns/mlflow.db`, artefacts dans `mlruns/artifacts/`) |
| rclone | datasets et sorties Colab sur Google Drive | `sudo apt install rclone` ; remote `gdrive` (voir [data-drive](data-drive.md)) |
| Colab | entraînements GPU (notebooks `notebooks/`) | badge « Open in Colab » de chaque notebook ; exécution GPU T4 |
| Label Studio | annotation | `docker run -p 8080:8080 heartexlabs/label-studio` |
| Hailo AI SW Suite | compilation HEF (x86 uniquement) | Docker, compte développeur Hailo |
| Mosquitto | broker MQTT | `sudo apt install mosquitto` |
| TimescaleDB + Grafana | séries temporelles et dashboard | `docker compose` (dans `backend/`) |
| PlatformIO | firmware ESP32 (XIAO ESP32-C6) | extension VS Code + plateforme pioarduino (core Arduino 3.x) |

### GPU : Colab en attendant le driver
Tant que la RTX locale n'est pas utilisable, les entraînements tournent sur Colab : le notebook clone le dépôt (public), installe `.[vision]`, monte le Drive et extrait les archives de `MyDrive/SerreIA/data/` sur le disque local de la session. Les sorties reviennent sur le PC par `make harvest`.

## 4. Conventions
- **Langue** : code et identifiants en anglais ; documentation et noms de classes de la taxonomie en français.
- **Style** : `ruff` (format + lint) ; type hints ; fonctions courtes.
- **Configs** : tout hyperparamètre dans un YAML de `configs/`, jamais codé en dur.
- **Reproductibilité** : seed fixée ; chaque run MLflow enregistre la config, le commit git, la version de la taxonomie et le hash de `index.parquet`.
- **Notebooks** : générés par `tools/notebooks/build.py` (`make notebooks`), versionnés sans sorties ; ne pas les éditer à la main.
- **Données** : `data/`, `data_archives/`, `mlruns/` et les poids (`*.pt`, `*.onnx`, `*.hef`) sont exclus de git (`.gitignore`).
- **Données téléchargées** : à traiter comme non fiables (aucun script exécuté depuis ces dossiers).
- **Tests** : `uv run pytest`, au minimum sur l'index (non-fuite, effectifs), la taxonomie (tous les dossiers mappés) et le format des messages MQTT (`tests/test_mqtt_contract.py`, ✅ en place).
- **Git** : `git init` à la racine ; branches par fonctionnalité (`feat/build-index`, …).
