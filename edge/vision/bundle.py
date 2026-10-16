"""Model bundle of the edge (docs/05 §6): `edge/models/<version>/` + `current` symlink.

manifest.json (written by vision.export.package):
    {"version": "clf-effb0-v3",
     "classifieur": {"onnx": "clf.onnx", "hef": "clf.hef", "size": 224, "labels": {...}},
     "detecteur": {"onnx": "yolo.onnx", "hef": "yolo.hef", "imgsz": 640,
                   "classes": ["feuille", "plante", "fruit"]},      # optional
     "patchcore": {"tomate": "patchcore_tomate.pt"}}                 # optional
`hef` entries are added once compiled (vision/export/hailo/); the version is the `modele`
field of the MQTT messages.
"""

import json
from pathlib import Path
from typing import Literal

from .backends import HailoBackend, OnnxBackend, shared_vdevice
from .classifier import EdgeClassifier
from .detector import EdgeYolo
from .pipeline import EdgePipeline, PatchCoreScorer

MANIFEST = "manifest.json"
BackendName = Literal["onnx", "hailo"]


def load_manifest(bundle: Path) -> dict:
    path = bundle / MANIFEST
    if not path.exists():
        raise FileNotFoundError(
            f"{path} absent : créer le bundle avec `python -m vision.export.package`"
        )
    return json.loads(path.read_text())


def _model_file(bundle: Path, entry: dict, backend: BackendName) -> Path:
    key = "hef" if backend == "hailo" else "onnx"
    if not entry.get(key):
        raise FileNotFoundError(f"pas de modèle {key} dans {bundle / MANIFEST} : {entry}")
    return bundle / entry[key]


def build_pipeline(
    bundle: Path,
    backend: BackendName = "onnx",
    conf: float = 0.25,
    margin: float = 0.1,
    patchcore: bool = True,
    device: str = "cpu",
) -> EdgePipeline:
    man = load_manifest(bundle)
    device_hailo = shared_vdevice() if backend == "hailo" else None

    def make(entry: dict, norm: str):
        path = _model_file(bundle, entry, backend)
        if backend == "hailo":
            return HailoBackend(path, device_hailo)
        return OnnxBackend(path, norm)

    clf = EdgeClassifier(make(man["classifieur"], "imagenet"), man["classifieur"]["labels"])
    detector = None
    if det := man.get("detecteur"):
        detector = EdgeYolo(
            make(det, "unit"), conf=conf, keep_class=det["classes"].index("feuille"),
            nms_on_chip=backend == "hailo",
        )  # fmt: skip
    scorer = None
    if patchcore and man.get("patchcore"):
        scorer = PatchCoreScorer({e: bundle / p for e, p in man["patchcore"].items()}, device)
    return EdgePipeline(clf, man["version"], detector, scorer, margin=margin)
