# Development environment (docs/08). `make setup` needs uv; without it, see the pip fallback.
PY ?= python
EXTRAS ?= --extra vision --extra notebook --extra backend --extra controle

setup:
	uv sync $(EXTRAS)

check-env:
	$(PY) -m tools.check_env

# After the NVIDIA driver: replaces the CPU build of torch by the PyPI one (CUDA on Linux,
# with its nvidia-* runtime wheels; no CUDA Toolkit needed).
cuda-torch:
	$(PY) -m pip uninstall -y torch torchvision
	$(PY) -m pip install torch torchvision
	$(PY) -c "import torch; print(torch.__version__, torch.cuda.is_available())"

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff format . && $(PY) -m ruff check .

mlflow:
	$(PY) -m mlflow ui --backend-store-uri sqlite:///mlruns/mlflow.db

# Harvest on the PC of the outputs copied to the Drive by the Colab notebooks
# (drive_data.sync_all, PeriodicSync; docs/data-drive.md): summaries, logs, tables and
# figures, without weights or checkpoints. `make harvest-all` also takes the checkpoints.
RUNS_REMOTE ?= gdrive:SerreIA/runs
OUTPUTS := runs reports mlruns/colab

harvest:
	for d in $(OUTPUTS); do rclone copy $(RUNS_REMOTE)/$$d $$d --include '*.json' \
		--include '*.csv' --include '*.md' --include '*.png' --include '*.txt' --include '*.db'; done

harvest-all:
	for d in $(OUTPUTS); do rclone copy $(RUNS_REMOTE)/$$d $$d --progress; done

# Phase 1 notebooks, regenerated from tools/notebooks/build.py.
notebooks:
	python -m tools.notebooks.build

# Server stack (docs/09 §7): TimescaleDB + Grafana (+ mosquitto for development).
# Database URL: $$SERREIA_DB, default postgresql+psycopg://serreia:serreia@localhost:5432/serreia
COMPOSE := docker compose -f backend/docker-compose.yml --profile broker

stack-up:
	$(COMPOSE) up -d

stack-down:
	$(COMPOSE) down

db-init:
	$(PY) -m backend.db.seed

ingest:
	$(PY) -m backend.ingestion

# HTTP API and web UI (docs/12): every route under /api, WS /ws/live, the built front on
# the same port; agent (docs/11; `--agent none` without it). SERREIA_UI_PASSWORD protects
# the writes.
api:
	$(PY) -m backend.api

# The UI without broker nor Pi: simulator + controller behind the API (docs/12 §5), the
# last 24 h caught up at start. PANNE=maladie:z1-A1/tomate/maladie/mildiou@15 for a proposal.
api-sim:
	$(PY) -m backend.api --mqtt sim --db sqlite:///data/serre_sim.db $(if $(PANNE),--panne $(PANNE))

# Web front (docs/12, frontend/): `front-dev` with `make api` or `make api-sim` alongside
# (Vite proxies /api and /ws to :8000); `front-build` for `make api` to serve it.
front-install:
	cd frontend && npm ci

front-dev:
	cd frontend && npm run dev

front-build:
	cd frontend && npm run build

front-test:
	cd frontend && npm run typecheck && npm test

# Pixel-art atlas of the game view (docs/13 §2): sprites-src/sprites.json + cut sprites →
# frontend/public/sprites/atlas.{png,json} and frontend/src/game/catalogue.gen.json.
sprites:
	$(PY) tools/construire_atlas.py

# OpenAPI schema of the backend → TypeScript types of the front.
openapi:
	$(PY) -m backend.api --openapi frontend/src/api/openapi.json
	cd frontend && npm run gen:api

# Playwright journey against the API with a simulated greenhouse (browser: npx playwright install chromium).
e2e:
	cd frontend && npm run build && npx playwright test

# Reference questions of the agent (docs/11 §6) with Claude: real API calls, tokens spent.
# Q=led-2h for one question; MODELE=claude-opus-5-5, EFFORT=high to compare.
agent-eval:
	$(PY) -m backend.agent.eval $(if $(Q),--question $(Q)) $(if $(MODELE),--modele $(MODELE)) $(if $(EFFORT),--effort $(EFFORT))

# Action tree of the last 24 h in the terminal (docs/10 §6); ZONE=z1 for one zone.
arbre:
	$(PY) -m backend.traceability $(if $(ZONE),--zone $(ZONE))

# Versioned serre.yaml rebuilt from the database (docs/09 §8), in data/serre_config/.
# INSTALL=<path> installs it for a local controller (not over the tracked example),
# PI_CONFIG=pi@serre.local:SerreIA/edge/controller/serre.yaml copies it to the Pi.
config-export:
	$(PY) -m backend.config.export $(if $(INSTALL),--install $(INSTALL)) $(if $(PI_CONFIG),--rsync $(PI_CONFIG))

# The last 24 h simulated at full speed and ingested (no broker), then the dashboard.
sim-demo:
	$(PY) -m backend.ingestion --sim --duree-h 24 --debut $$(date -u -d '-24 hours' +%Y-%m-%dT%H:%M:%S+00:00)

# Real-time simulator + controller on the broker (run `make ingest` alongside).
sim-live:
	$(PY) -m sim --avec-controleur

.PHONY: setup check-env cuda-torch test lint mlflow harvest harvest-all notebooks stack-up stack-down db-init ingest api api-sim front-install front-dev front-build front-test openapi e2e agent-eval arbre config-export sim-demo sim-live
