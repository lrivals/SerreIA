"""Datasets archived on Google Drive: get_datasets.sh pack/unpack and drive_data.prepare_data."""

import os
import shutil
import subprocess

import pytest

from tools.notebooks import drive_data

SCRIPT = drive_data.GET_DATASETS

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("tar") is None, reason="bash and tar required"
)


def _sh(*args, data_dir, archive_dir=None):
    env = dict(os.environ, DATA_DIR=str(data_dir))
    if archive_dir:
        env["ARCHIVE_DIR"] = str(archive_dir)
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True)


def _tar_names(path) -> list[str]:
    out = subprocess.run(["tar", "-tf", str(path)], capture_output=True, text=True, check=True)
    return out.stdout.split()


def _plantvillage(data):
    """Marker folder, a linked folder, grayscale/ (excluded) and files that must stay out."""
    (data / "raw").mkdir(parents=True)
    (data / "raw" / "img.jpg").write_bytes(b"jpg")
    pv = data / "plantvillage"
    (pv / "segmented" / "Tomato___healthy").mkdir(parents=True)
    (pv / "segmented" / "Tomato___healthy" / "a_final_masked.jpg").write_bytes(b"jpg")
    (pv / "grayscale").mkdir()
    (pv / "grayscale" / "g.jpg").write_bytes(b"jpg")
    (pv / "color").symlink_to("../raw")
    (pv / "dl.zip").write_bytes(b"zip")
    (pv / "dl.part").write_bytes(b"partial")


def test_pack_unpack_roundtrip(tmp_path):
    src, arch, dst = tmp_path / "src", tmp_path / "arch", tmp_path / "dst"
    _plantvillage(src)
    assert _sh("pack", "plantvillage", data_dir=src, archive_dir=arch).returncode == 0
    assert (arch / "plantvillage.tar").is_file()
    assert not (arch / "plantvillage.tar.part").exists()
    names = _tar_names(arch / "plantvillage.tar")
    assert "plantvillage/segmented/Tomato___healthy/a_final_masked.jpg" in names
    assert not any(n.endswith((".zip", ".part")) for n in names)
    assert not any("grayscale" in n for n in names)

    assert _sh("ready", "plantvillage", data_dir=dst).returncode == 1
    assert _sh("unpack", str(arch), "plantvillage", data_dir=dst).returncode == 0
    assert _sh("ready", "plantvillage", data_dir=dst).returncode == 0
    # Links followed when packing: real files, no more link to data/raw.
    img = dst / "plantvillage" / "color" / "img.jpg"
    assert img.is_file() and not (dst / "plantvillage" / "color").is_symlink()


def test_pack_several_paths(tmp_path):
    src, arch = tmp_path / "src", tmp_path / "arch"
    src.mkdir()
    (src / "index.parquet").write_bytes(b"pq")
    (src / "index_rejets.txt").write_text("")
    (src / "ccmt").mkdir()  # not part of the index archive
    assert _sh("pack", "index", data_dir=src, archive_dir=arch).returncode == 0
    assert sorted(_tar_names(arch / "index.tar")) == ["index.parquet", "index_rejets.txt"]


def test_pack_missing_and_unknown(tmp_path):
    assert _sh("pack", "ccmt", data_dir=tmp_path).returncode != 0
    assert _sh("ready", "nope", data_dir=tmp_path).returncode != 0


def test_prepare_data_ways(tmp_path):
    src, drive, dst = tmp_path / "src", tmp_path / "drive", tmp_path / "dst"
    _plantvillage(src)
    assert _sh("pack", "plantvillage", data_dir=src, archive_dir=drive / "data").returncode == 0
    # Mounted Drive (Colab): archive extracted, then the dataset is ready.
    way = drive_data.prepare_data(
        "plantvillage", drive_dir=drive, data_dir=dst, download=False, remote=None
    )
    assert way == "drive"
    assert drive_data.prepare_data("plantvillage", drive_dir=drive, data_dir=dst) == "ready"


def test_prepare_data_nothing(tmp_path):
    with pytest.raises(RuntimeError, match="push backgrounds"):
        drive_data.prepare_data(
            "backgrounds", drive_dir=None, data_dir=tmp_path, download=False, remote=None
        )


def test_periodic_sync_inactive_outside_colab():
    with drive_data.PeriodicSync(drive_data.OUTPUTS) as sync:
        assert not sync.active
    assert sync.srcs == drive_data.OUTPUTS
