"""Build the printed parts (docs/20) into STEP + STL files, run by FreeCAD:

    freecadcmd hardware/build.py                                  # or: make hardware
    SERREIA_PIECES=clip_bache,couvercle_cuve freecadcmd hardware/build.py
    SERREIA_HW_OUT=/tmp/hw freecadcmd hardware/build.py

freecadcmd takes no script arguments, hence the environment variables. Also runs with a
Python that can import FreeCAD (`python3 hardware/build.py`, FreeCAD's lib directory is
searched in the usual places). Not meant to be imported.

Checks the dimensions first (`params.verifier`, blocking) and lists the ones still nominal
(warning). Each part must be a valid solid that fits the printer; output in
`<out>/<module>/<name>.step|.stl`. Exit code 1 if anything fails.
"""

import importlib
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for lib in ("/usr/lib/freecad/lib", "/usr/lib/freecad-python3/lib", "/usr/local/lib/freecad/lib"):
    if Path(lib).is_dir() and lib not in sys.path:
        sys.path.append(lib)

import FreeCAD  # noqa: E402,F401  (initialises the Part module)
import Part  # noqa: E402,F401

from hardware import PIECES, params  # noqa: E402

DEFLEXION = 0.05  # mm, STL chord tolerance


def exporter(shape, base: Path) -> None:
    base.parent.mkdir(parents=True, exist_ok=True)
    shape.exportStep(str(base.with_suffix(".step")))
    try:
        import MeshPart

        mesh = MeshPart.meshFromShape(
            Shape=shape, LinearDeflection=DEFLEXION, AngularDeflection=0.26, Relative=False
        )
        mesh.write(str(base.with_suffix(".stl")))
    except ImportError:
        shape.exportStl(str(base.with_suffix(".stl")))


def controler(shape) -> str | None:
    """Why `shape` cannot be printed, or None."""
    if shape.isNull() or not shape.Solids:
        return "no solid"
    if not shape.isValid():
        return "invalid shape"
    if shape.Volume <= 0:
        return "null volume"
    bb = shape.BoundBox
    if max(bb.XLength, bb.YLength, bb.ZLength) > params.VOLUME_IMPRESSION:
        return f"{bb.XLength:.0f} × {bb.YLength:.0f} × {bb.ZLength:.0f} mm > printer volume"
    return None


def main() -> int:
    p = params.load()
    err = params.verifier(p)
    for e in err:
        print(f"FAIL dimensions: {e}")
    if err:
        return 1
    if reste := params.non_mesurees():
        print(f"WARN nominal dimensions (hardware/mesures.toml): {', '.join(reste)}")
    noms = [n for n in os.environ.get("SERREIA_PIECES", "").split(",") if n] or list(PIECES)
    if inconnus := sorted(set(noms) - set(PIECES)):
        print(f"FAIL unknown parts {inconnus}, known: {', '.join(PIECES)}")
        return 1
    out = Path(os.environ.get("SERREIA_HW_OUT", ROOT / "hardware" / "build"))
    echecs = 0
    for nom in noms:
        try:
            formes = importlib.import_module(f"hardware.pieces.{nom}").pieces(p)
        except Exception:
            print(f"FAIL {nom}:\n{traceback.format_exc()}")
            echecs += 1
            continue
        for sous, forme in formes.items():
            if raison := controler(forme):
                print(f"FAIL {nom}/{sous}: {raison}")
                echecs += 1
                continue
            exporter(forme, out / nom / sous)
            bb = forme.BoundBox
            print(
                f"OK   {nom}/{sous}: {bb.XLength:.0f} × {bb.YLength:.0f} × {bb.ZLength:.0f} mm,"
                f" {forme.Volume / 1000:.1f} cm³"
            )
    print(f"{'FAIL' if echecs else 'OK'}: {echecs} failure(s), output in {out}")
    return 1 if echecs else 0


code = main()
sys.stdout.flush()
os._exit(code)  # the exit code reaches the shell even when run by freecadcmd
