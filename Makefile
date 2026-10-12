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

.PHONY: harvest harvest-all notebooks
