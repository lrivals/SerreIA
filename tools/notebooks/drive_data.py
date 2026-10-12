"""Datasets and notebook outputs on Google Drive (docs/data-drive.md).

Adapted from the drive-data-archives system (EmbeddedComputervision).

Datasets are not versioned. `prepare_data` puts one in data/ (on Colab, the local disk of
the session) by trying, in order:

1. the marker of `tools/get_datasets.sh` (already ready: used as is);
2. the archive `<drive_dir>/data/<ds>.tar` on the mounted Drive (Colab), uploaded from the PC
   by `tools/get_datasets.sh push <ds>`;
3. the same archive through rclone (`get_datasets.sh pull <ds>`): a PC without the dataset;
4. the direct download (`get_datasets.sh download <ds>`), if the dataset has one.

Files are never read through the Drive mount (slow for thousands of small files): only the
tar is read there, in one go. Outputs (checkpoints included) go to `<drive_dir>/runs/`
under the same relative path as in the repository.

No dependency outside the standard library: this module is imported by the notebooks.
"""

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GET_DATASETS = ROOT / "tools" / "get_datasets.sh"
PROJECT = "SerreIA"
DRIVE_MOUNT = "/content/drive"
DRIVE_DIR = f"{DRIVE_MOUNT}/MyDrive/{PROJECT}"  # data/*.tar, runs/
DRIVE_REMOTE = f"gdrive:{PROJECT}/data"  # the same data/ folder, seen by rclone
# Notebook outputs, relative to ROOT: checkpoints, evaluation reports, MLflow base of Colab
# (separate from the PC's mlruns/mlflow.db, so that harvesting never overwrites it).
OUTPUTS = ("runs", "reports", "mlruns/colab")
COLAB_MLFLOW = "mlruns/colab/mlflow.db"


def in_colab():
    return "google.colab" in sys.modules


def mount_drive():
    """Mounts Google Drive on /content/drive (asks for the authorisation in the notebook)."""
    if not Path(DRIVE_MOUNT, "MyDrive").exists():
        from google.colab import drive

        drive.mount(DRIVE_MOUNT)


def _env(data_dir=None, **extra):
    return dict(os.environ, **({"DATA_DIR": str(data_dir)} if data_dir else {}), **extra)


def _sh(cmd, data_dir=None, **extra):
    print("$ " + " ".join(cmd), flush=True)
    return subprocess.run(["bash", *cmd], cwd=ROOT, env=_env(data_dir, **extra)).returncode


def ready(dataset, data_dir=None):
    """Marker of the dataset present (`get_datasets.sh ready`)?"""
    return (
        subprocess.run(
            ["bash", str(GET_DATASETS), "ready", dataset],
            cwd=ROOT,
            env=_env(data_dir),
            capture_output=True,
        ).returncode
        == 0
    )


def prepare_data(dataset, drive_dir=DRIVE_DIR, data_dir=None, download=True, remote=DRIVE_REMOTE):
    """Puts `dataset` in data/ (or `data_dir`); returns the way taken: ready, drive, rclone,
    download. `drive_dir` (mounted Drive) or `remote` (rclone) set to None: way disabled.

    Raises RuntimeError with what to do if no way succeeds."""
    if ready(dataset, data_dir):
        print(f"{dataset}: ready")
        return "ready"
    archives = Path(drive_dir) / "data" if drive_dir else None
    if archives and (archives / f"{dataset}.tar").is_file():
        if _sh([str(GET_DATASETS), "unpack", str(archives), dataset], data_dir) == 0:
            return "drive"
    if remote and shutil.which("rclone"):
        if _sh([str(GET_DATASETS), "pull", dataset], data_dir, DRIVE_REMOTE=remote) == 0:
            return "rclone"
    if download:
        if _sh([str(GET_DATASETS), "download", dataset], data_dir) == 0 and ready(
            dataset, data_dir
        ):
            return "download"
    raise RuntimeError(
        f"{dataset} not found. On the PC that has it: tools/get_datasets.sh push {dataset} "
        f"(pack, then rclone to {remote or DRIVE_REMOTE}); see docs/data-drive.md."
    )


def ensure(datasets, drive_dir=DRIVE_DIR):
    """`prepare_data` of each dataset, the way the notebooks do it: Colab through the mounted
    Drive, local PC through rclone only (never an implicit download)."""
    for ds in datasets:
        if in_colab() and drive_dir:
            prepare_data(ds, drive_dir=drive_dir)
        else:
            prepare_data(ds, drive_dir=None, download=False)


def sync_outputs(src="runs", drive_dir=DRIVE_DIR):
    """Copies the outputs (checkpoints included) into `<drive_dir>/runs/<src>`, to survive
    the end of the session; returns the destination folder."""
    dst = Path(drive_dir) / "runs" / src
    shutil.copytree(ROOT / src, dst, dirs_exist_ok=True)
    print(f"{src} → {dst}")
    return dst


def restore_outputs(src="runs", drive_dir=DRIVE_DIR):
    """Inverse of `sync_outputs` at the start of a session: resume from the last checkpoint."""
    saved = Path(drive_dir) / "runs" / src
    if saved.is_dir():
        shutil.copytree(saved, ROOT / src, dirs_exist_ok=True)
        print(f"{saved} → {src}")
    return saved.is_dir()


def sync_all(drive_dir=DRIVE_DIR):
    """`sync_outputs` of every folder of OUTPUTS that exists (Colab, Drive mounted)."""
    if not (in_colab() and drive_dir and Path(drive_dir).is_dir()):
        return
    for src in OUTPUTS:
        if (ROOT / src).is_dir():
            sync_outputs(src, drive_dir)


def restore_all(drive_dir=DRIVE_DIR):
    """`restore_outputs` of every folder of OUTPUTS (start of a Colab session)."""
    for src in OUTPUTS:
        restore_outputs(src, drive_dir)


class PeriodicSync:
    """`with PeriodicSync(OUTPUTS):` copies the folders to the Drive every `period` s
    and once more at the exit of the block (even on error or interruption). Nothing outside
    Colab or without a mounted Drive. A failed copy is printed, never raised."""

    def __init__(self, src="runs", drive_dir=DRIVE_DIR, period=600):
        self.srcs = (src,) if isinstance(src, str) else tuple(src)
        self.drive_dir, self.period = drive_dir, period
        self.active = in_colab() and bool(drive_dir) and Path(drive_dir).is_dir()
        self._stop = threading.Event()

    def _copy(self):
        for src in self.srcs:
            try:
                if (ROOT / src).is_dir():
                    sync_outputs(src, self.drive_dir)
            except Exception as e:  # noqa: BLE001  (best-effort copy)
                print(f"sync {src}: {e.__class__.__name__}: {e}")

    def _loop(self):
        while not self._stop.wait(self.period):
            self._copy()

    def __enter__(self):
        if self.active:
            threading.Thread(target=self._loop, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self.active:
            self._copy()
        return False
