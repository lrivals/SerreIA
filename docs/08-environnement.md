# 08 — Environnement de développement

## 1. Poste d'entraînement (PC actuel)
- CPU : 22 threads ; RAM : 62 Go ; disque : ≈ 1,2 To libres
- GPU : **NVIDIA RTX 1000 Ada Laptop (6 Go)**, plus un iGPU Intel Arc
- Python 3.12
- Node.js ≥ 20 et npm (interface web, `frontend/`, doc 12) ; Playwright : `cd frontend && npx playwright install chromium`

### Driver NVIDIA (à faire en premier)
`nvidia-smi` ne répond pas actuellement : aucun driver propriétaire installé (seuls des restes du 535 en état `rc`). Driver recommandé par `ubuntu-drivers devices` : **`nvidia-driver-595-open`**.
```bash
ubuntu-drivers devices                 # driver recommandé
sudo ubuntu-drivers install            # ou : sudo apt install nvidia-driver-595-open
sudo reboot
nvidia-smi                             # doit afficher la RTX 1000 Ada
make cuda-torch                        # torch CUDA à la place du build CPU
make check-env                         # tout doit être OK
```
Secure Boot actif : choisir un mot de passe MOK pendant l'installation, puis « Enroll MOK » sur l'écran bleu au redémarrage.
Pas besoin d'installer CUDA Toolkit séparément : les wheels PyTorch embarquent le runtime CUDA.

## 2. Gestion du projet Python avec `uv`
Le `pyproject.toml` existe déjà. Les dépendances sont réparties en groupes :

| Groupe | Contenu | Installation |
|---|---|---|
| base | `pydantic`, `paho-mqtt` (contrat MQTT) | `uv sync` |
| `vision` | torch, torchvision, timm, albumentations, OpenCV, pandas, pyarrow, imagehash, scikit-learn, MLflow, grad-cam, ONNX… | `uv sync --extra vision` |
| `detection` | ultralytics (YOLO, AGPL-3.0), sam2, scipy (phase 2, doc 04) | `uv sync --extra vision --extra detection` |
| `controle` | numpy, pandas, pyyaml, onnxruntime (contrôleur et simulateur, doc 06 ; torch de `vision` pour entraîner le GRU) | `uv sync --extra controle` |
| `notebook` | ipykernel, nbclient, nbformat, ipywidgets (notebooks en local) | `uv sync --extra notebook` |
| `backend` | SQLAlchemy, psycopg, pyyaml, FastAPI, uvicorn, websockets, anthropic (base, ingestion, API, agent ; docs 09, 11, 12) | `uv sync --extra backend --extra controle` |
| `dev` | pytest, ruff | inclus par défaut dans `uv sync` |

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync                                        # base + dev
uv sync --extra vision                         # poste d'entraînement
uv run pytest                                  # tests
uv run ruff format . && uv run ruff check .    # style
uv run python -c "import torch; print(torch.cuda.is_available())"
```
`make setup` équivaut à `uv sync --extra vision --extra notebook --extra backend --extra controle` (poste d'entraînement complet ; `EXTRAS=…` pour en changer).

Le `.venv` actuel contient **torch CPU** (`2.14.1+cpu`, installé par le repli pip) : une fois le driver installé, `make cuda-torch` le remplace par le wheel PyPI, qui embarque le runtime CUDA sur Linux et supporte l'Ada (sm_89). Pas d'index PyTorch spécifique nécessaire ; pour une version CUDA précise, ajouter l'index `https://download.pytorch.org/whl/cu12x` dans `[tool.uv]`.
La détection d'anomalies (PatchCore, `vision/anomaly/patchcore.py`) est implémentée sans anomalib.

**Diagnostic** : `make check-env` (`tools/check_env.py`) vérifie Python, uv, le driver, torch/CUDA, les extras installés, rclone (remote `gdrive:`), docker et mosquitto ; code retour 1 si un point bloquant manque.

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
| MLflow | suivi des expériences | `make mlflow` (= `mlflow ui --backend-store-uri sqlite:///mlruns/mlflow.db`) (SQLite local `mlruns/mlflow.db`, artefacts dans `mlruns/artifacts/`) |
| rclone | datasets et sorties Colab sur Google Drive | `sudo apt install rclone` ; remote `gdrive` (voir [data-drive](data-drive.md)) |
| Colab | entraînements GPU (notebooks `notebooks/`) | badge « Open in Colab » de chaque notebook ; exécution GPU T4 |
| Label Studio | annotation | `docker run -p 8080:8080 heartexlabs/label-studio` |
| Hailo AI SW Suite | compilation HEF (x86 uniquement) | Docker, compte développeur Hailo |
| Mosquitto | broker MQTT | `sudo apt install mosquitto` |
| TimescaleDB + Grafana | séries temporelles et dashboard | `make stack-up` (`backend/docker-compose.yml`, + mosquitto de développement) ; base : `$SERREIA_DB` |
| PlatformIO | firmware ESP32 (XIAO ESP32-C6) | extension VS Code + plateforme pioarduino (core Arduino 3.x) |

### GPU : Colab en attendant le driver
Tant que la RTX locale n'est pas utilisable, les entraînements tournent sur Colab : le notebook clone le dépôt (public), installe `.[vision]`, monte le Drive et extrait les archives de `MyDrive/SerreIA/data/` sur le disque local de la session. Les sorties reviennent sur le PC par `make harvest`.

## 4. Conventions
- **Langue** : code et identifiants en anglais ; documentation et noms de classes de la taxonomie en français.
- **Style** : `ruff` (format + lint, `make lint`) ; type hints ; fonctions courtes.
- **Configs** : tout hyperparamètre dans un YAML de `configs/`, jamais codé en dur.
- **Reproductibilité** : seed fixée ; chaque run MLflow enregistre la config, le commit git, la version de la taxonomie et le hash de `index.parquet`.
- **Notebooks** : générés par `tools/notebooks/build.py` (`make notebooks`), versionnés sans sorties ; ne pas les éditer à la main.
- **Données** : `data/`, `data_archives/`, `mlruns/` et les poids (`*.pt`, `*.onnx`, `*.hef`) sont exclus de git (`.gitignore`).
- **Données téléchargées** : à traiter comme non fiables (aucun script exécuté depuis ces dossiers).
- **Tests** : `make test` (`pytest`), au minimum sur l'index (non-fuite, effectifs), la taxonomie (tous les dossiers mappés) et le format des messages MQTT (`tests/test_mqtt_contract.py`, ✅ en place).
- **Git** : `git init` à la racine ; branches par fonctionnalité (`feat/build-index`, …).
