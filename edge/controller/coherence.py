"""Configuration consistency (docs/09 §2–§3): warnings, not errors.

A configuration that `SerreCfg` accepts can still be inconsistent with the growing modes
or the vision taxonomy; the controller runs with it but the problems are logged at load
time, by the seed and by the export (and shown by the UI with G2).
"""

from functools import cache

from common.mqtt import Actuator, SensorType

from .config import HYDRO, SerreCfg

DOSING = (Actuator.POMPE_PH_DOWN, Actuator.POMPE_NUTRI_A, Actuator.POMPE_NUTRI_B)


@cache
def known_species() -> frozenset[str]:
    """Species the classifier knows (`vision/datasets/taxonomy.yaml`); empty if the vision
    package or the taxonomy file is missing (every plant is then out of taxonomy)."""
    try:
        from vision.datasets.taxonomy import load_taxonomy

        return frozenset(load_taxonomy().especes)
    except (ImportError, OSError):
        return frozenset()


def check(cfg: SerreCfg, especes: set[str] | frozenset[str]) -> list[str]:
    out = []
    for z in cfg.zones:
        measured = {
            m for c in cfg.capteurs if c.zone == z.id and (c.cuve or c.emplacement is None)
            for m in c.mesures
        }  # fmt: skip
        for e in z.emplacements:
            if e.mode_culture in HYDRO:
                missing = [m for m in (SensorType.PH, SensorType.EC) if m not in measured]
                if missing:
                    where = f"la cuve {z.cuve_id}" if z.cuve_id else f"la zone {z.id}"
                    out.append(
                        f"{e.id} : emplacement {e.mode_culture} sans capteur "
                        f"{' ni '.join(missing)} dans {where}"
                    )
        for a in cfg.actionneurs:
            if a.zone == z.id and a.type in DOSING and not z.hydro:
                out.append(f"{a.id} : pompe doseuse dans {z.id}, sans emplacement hydro")
        for e in z.emplacements:
            if e.plante is not None and e.plante.espece not in especes:
                out.append(
                    f"{e.plante.id} : espèce {e.plante.espece} hors taxonomie, classification "
                    "vision affichée sans décision automatique"
                )
    for cam in cfg.cameras:
        if len(cam.emplacements_visibles) > 1:
            without = [e for e in cam.emplacements_visibles if e not in cam.regions]
            if without:
                out.append(
                    f"{cam.id} : voit plusieurs emplacements, sans région pour "
                    f"{', '.join(without)} (résultats non rattachés)"
                )
    return out
