"""Export chain to the edge (docs/05 §2, §6): calibration set, bundle, `current` symlink,
bundle loaded by the edge. Untrained model (pretrained=False): no training here."""

import json
from datetime import UTC, datetime

import cv2
import numpy as np
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("onnxruntime")
pytest.importorskip("timm")

from edge.vision.bundle import build_pipeline, load_manifest  # noqa: E402
from vision.export.calibration import build_calibration, calibration_paths  # noqa: E402
from vision.export.package import add_hef, package, parse_patchcore, set_current  # noqa: E402

LABELS = {
    "especes": ["fraisier", "tomate"],
    "sante": ["sain", "anormal"],
    "classes": ["fraisier/sain/sain", "tomate/maladie/mildiou", "tomate/sain/sain"],
    "taxonomy_version": 1,
}


def _images(folder, n, shape=(50, 80)):
    folder.mkdir(parents=True)
    for i in range(n):
        img = np.full((*shape, 3), (40 * i % 255, 120, 60), np.uint8)
        cv2.imwrite(str(folder / f"{i:03d}.jpg"), img)
    return folder


def test_calibration_set(tmp_path):
    serre = _images(tmp_path / "serre", 5)
    paths = calibration_paths(3, tmp_path, serre)  # more greenhouse images than needed
    assert len(paths) == 3 and all(p.parent == serre for p in paths)
    paths = calibration_paths(10, tmp_path, serre)  # no index: greenhouse images only
    assert len(paths) == 5
    clf = build_calibration(paths, 32)
    assert clf.shape == (5, 32, 32, 3) and clf.dtype == np.uint8
    yolo = build_calibration(paths, 64, "yolo")
    assert yolo.shape == (5, 64, 64, 3)
    assert (yolo[0, 0] == 114).all()  # letterbox padding (80x50 image)


@pytest.fixture
def checkpoint(tmp_path):
    from vision.datasets.dataset import LabelSpace
    from vision.models.multihead import build_model
    from vision.train.config import load_config
    from vision.train.train_classifier import ROOT, save_checkpoint

    cfg = load_config(ROOT / "configs/clf_effnet_b0.yaml")
    cfg["data"]["size"] = 32
    labels = LabelSpace.from_dict(LABELS)
    model = build_model(cfg, labels.sizes(), pretrained=False)
    path = tmp_path / "run" / "best.pt"
    save_checkpoint(path, model, cfg, labels)
    return path


def test_package_bundle_and_edge_pipeline(tmp_path, checkpoint):
    models = tmp_path / "models"
    bank = tmp_path / "tomate.pt"
    bank.write_bytes(b"banque")
    bundle = package(checkpoint, "clf-test-v1", patchcore=parse_patchcore([f"tomate={bank}"]),
                     n=0, models_dir=models)  # fmt: skip
    man = load_manifest(bundle)
    assert man["version"] == "clf-test-v1"
    assert man["classifieur"]["labels"] == LABELS and man["classifieur"]["size"] == 32
    assert (bundle / "clf.onnx").exists() and (bundle / "patchcore_tomate.pt").exists()
    assert man["patchcore"] == {"tomate": "patchcore_tomate.pt"}
    assert "detecteur" not in man and "hef" not in man["classifieur"]
    with pytest.raises(FileExistsError):
        package(checkpoint, "clf-test-v1", n=0, models_dir=models)
    with pytest.raises(ValueError):
        package(checkpoint, "current", n=0, models_dir=models)

    current = set_current(models, "clf-test-v1")
    assert current.is_symlink() and current.resolve() == bundle.resolve()
    with pytest.raises(FileNotFoundError):
        set_current(models, "absente")

    (bundle / "clf.hef").write_bytes(b"hef")
    assert add_hef(bundle)["classifieur"]["hef"] == "clf.hef"

    # The edge loads the bundle through `current`, ONNX backend, without PatchCore.
    pipe = build_pipeline(current, "onnx", patchcore=False)
    img = np.random.default_rng(0).integers(0, 255, (120, 160, 3), np.uint8)
    result, extras = pipe(img, "cam-z1-a", datetime(2026, 10, 12, tzinfo=UTC))
    assert result.modele == "clf-test-v1" and result.detections[0].bbox is None
    d = result.detections[0]
    assert d.espece in LABELS["especes"] and d.classe in LABELS["classes"]
    json.dumps(extras, allow_nan=False)
