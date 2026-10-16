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
PY ?= python
COMPOSE := docker compose -f backend/docker-compose.yml --profile broker

stack-up:
	$(COMPOSE) up -d

stack-down:
	$(COMPOSE) down

db-init:
	$(PY) -m backend.db.seed

ingest:
	$(PY) -m backend.ingestion

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

.PHONY: harvest harvest-all notebooks stack-up stack-down db-init ingest config-export sim-demo sim-live
