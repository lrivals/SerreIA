"""Model bundle for the edge (docs/05 §2, §6): `edge/models/<version>/` + `current` symlink.

    python -m vision.export.package --classifier <run_id|best.pt> --version clf-effb0-v1 \\
        [--detector runs/<yolo>/best.pt] [--patchcore tomate=runs/patchcore/tomate.pt] [--n 256]
    python -m vision.export.package --add-hef edge/models/clf-effb0-v1   # after hailo/
    python -m vision.export.package --set-current clf-effb0-v1

Exports the classifier (ONNX + comparison with PyTorch on n val images, 0: none), the YOLO
detector (ONNX) and copies the PatchCore banks, then writes manifest.json, read by
edge/vision/bundle.py. The version is the `modele` field of the MQTT messages.
"""

import argparse
import json
import logging
import os
import re
import shutil
from pathlib import Path

from edge.vision.bundle import MANIFEST

log = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parents[2] / "edge" / "models"
CURRENT = "current"
_VERSION_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def write_manifest(bundle: Path, manifest: dict) -> Path:
    path = bundle / MANIFEST
    path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    return path


def set_current(models_dir: Path, version: str) -> Path:
    """Atomic switch of the relative `current` symlink."""
    if not (models_dir / version / MANIFEST).exists():
        raise FileNotFoundError(f"bundle {models_dir / version} sans {MANIFEST}")
    tmp = models_dir / f".{CURRENT}.tmp"
    tmp.unlink(missing_ok=True)
    tmp.symlink_to(version, target_is_directory=True)
    os.replace(tmp, models_dir / CURRENT)
    return models_dir / CURRENT


def add_hef(bundle: Path) -> dict:
    """Registers clf.hef / yolo.hef found in the bundle."""
    man = json.loads((bundle / MANIFEST).read_text())
    for key, name in (("classifieur", "clf.hef"), ("detecteur", "yolo.hef")):
        if man.get(key) and (bundle / name).exists():
            man[key]["hef"] = name
    write_manifest(bundle, man)
    return man


def parse_patchcore(specs: list[str]) -> dict[str, Path]:
    out = {}
    for s in specs:
        espece, sep, path = s.partition("=")
        p = Path(path if sep else espece)
        out[espece if sep else p.stem] = p
    return out


def package(
    classifier: Path,
    version: str,
    detector: Path | None = None,
    patchcore: dict[str, Path] | None = None,
    n: int = 256,
    models_dir: Path = MODELS_DIR,
    force: bool = False,
) -> Path:
    from vision.export.to_onnx import export_and_check

    if not _VERSION_RE.match(version) or version == CURRENT:
        raise ValueError(f"version invalide : {version!r}")
    bundle = models_dir / version
    if bundle.exists():
        if not force:
            raise FileExistsError(f"{bundle} existe déjà (--force pour le remplacer)")
        shutil.rmtree(bundle)
    bundle.mkdir(parents=True)

    res = export_and_check(classifier, n, bundle / "clf.onnx")
    if res:
        worst = res["worst_disagree_pts"]
        log.info("ONNX vs PyTorch : %.2f pt de désaccord max (critère < 0,5)", worst)
        if worst >= 0.5:
            log.warning("écart ONNX / PyTorch au-dessus du critère de docs/03 §6")
    meta = json.loads((bundle / "clf.json").read_text())
    manifest: dict = {
        "version": version,
        "classifieur": {
            "onnx": "clf.onnx",
            "size": meta["size"],
            "labels": meta["labels"],
            "source": str(classifier),
        },  # fmt: skip
    }
    if detector is not None:
        from vision.export.yolo_onnx import export_yolo

        manifest["detecteur"] = {
            **export_yolo(detector, bundle / "yolo.onnx"),
            "source": str(detector),
        }
    if patchcore:
        manifest["patchcore"] = {}
        for espece, path in patchcore.items():
            name = f"patchcore_{espece}.pt"
            shutil.copy(path, bundle / name)
            manifest["patchcore"][espece] = name
    write_manifest(bundle, manifest)
    return bundle


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--classifier", help="run MLflow (runs/<id>/best.pt) ou chemin de best.pt")
    g.add_argument("--add-hef", type=Path, help="bundle où enregistrer clf.hef / yolo.hef")
    g.add_argument("--set-current", metavar="VERSION")
    parser.add_argument("--version", help="ex. clf-effb0-v1 (champ `modele` des messages)")
    parser.add_argument("--detector", type=Path, default=None, help="best.pt YOLO")
    parser.add_argument("--patchcore", nargs="*", default=[], help="espece=chemin.pt")
    parser.add_argument("--n", type=int, default=256, help="images val de vérification ONNX")
    parser.add_argument("--models-dir", type=Path, default=MODELS_DIR)
    parser.add_argument("--no-current", action="store_true", help="ne pas basculer `current`")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.add_hef:
        print(json.dumps(add_hef(args.add_hef), indent=1, ensure_ascii=False)[:2000])
        return
    if args.set_current:
        print(f"{set_current(args.models_dir, args.set_current)} -> {args.set_current}")
        return
    if not args.version:
        parser.error("--version est requis avec --classifier")
    from vision.train.train_classifier import RUNS_DIR

    ckpt = Path(args.classifier)
    if not ckpt.exists():
        ckpt = RUNS_DIR / args.classifier / "best.pt"
    bundle = package(ckpt, args.version, args.detector, parse_patchcore(args.patchcore),
                     args.n, args.models_dir, args.force)  # fmt: skip
    print(f"bundle : {bundle}")
    if not args.no_current:
        print(f"{set_current(args.models_dir, args.version)} -> {args.version}")


if __name__ == "__main__":
    main()
