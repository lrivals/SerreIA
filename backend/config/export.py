"""Export the greenhouse configuration from the database to the Pi (docs/09 §8).

    python -m backend.config.export        # data/serre_config/serre_config_v<N>.yaml
    python -m backend.config.export --install edge/controller/serre.yaml
    python -m backend.config.export --rsync pi@serre.local:SerreIA/edge/controller/serre.yaml

The database is the source of the configuration (seeded from serre.yaml until the UI of
G2): the export rebuilds a complete, self-contained serre.yaml (recipes inline), checks it
like the controller does (`SerreCfg`, recipes of every plant, consistency warnings) and
gives it a version. The version only changes with the content: an unchanged configuration
keeps its number, a new one gets N + 1, recorded in `config_export` and in
`serre.config_version`. The controller hot-reloads the installed file and records that
version in every decision, so a decision can be replayed with the exact configuration.
Transport: a local copy (atomic) or rsync; the retained topic `serre/config` is still a
proposal outside the contract.
"""

import argparse
import hashlib
import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from common.mqtt import SensorType
from edge.controller.config import Greenhouse, SerreCfg

from ..db import models as m
from ..db.seed import ACTIONNEUR_PARAMETRES, PARAMETRES
from ..db.session import init_db, make_engine, make_sessions

log = logging.getLogger(__name__)

DEFAULT_OUT = Path("data/serre_config")
_MESURES = list(SensorType)


@dataclass
class Export:
    version: int
    cfg: SerreCfg
    changed: bool
    warnings: list[str]

    def yaml(self) -> str:
        return render(self.cfg)


def _drop_none(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


def build_config(session: Session) -> dict:
    """serre.yaml content (without `config_version`) rebuilt from the database alone."""
    serre = session.scalars(select(m.Serre)).first()
    if serre is None:
        raise RuntimeError("aucune serre en base : lancer d'abord python -m backend.db.seed")
    params = dict(serre.parametres or {})
    params["lumiere"] = {**params.get("lumiere", {}), "lux_vers_ppfd": serre.lux_vers_ppfd}

    active = {
        a.emplacement_id: a.plante_id
        for a in session.scalars(select(m.Affectation).where(m.Affectation.fin.is_(None)))
    }
    zones = []
    for z in session.scalars(select(m.Zone).order_by(m.Zone.id)):
        emplacements = []
        for e in session.scalars(
            select(m.Emplacement).where(m.Emplacement.zone_id == z.id).order_by(m.Emplacement.id)
        ):
            emp = {"id": e.id, "mode_culture": e.mode_culture}
            if e.contenant_id is not None and (c := session.get(m.Contenant, e.contenant_id)):
                emp["contenant"] = _drop_none(
                    dict(type=c.type, volume_l=c.volume_l, materiau=c.materiau, drainage=c.drainage)
                )
            if (pid := active.get(e.id)) is not None:
                p = session.get(m.Plante, pid)
                emp["plante"] = _drop_none(
                    dict(
                        id=p.id,
                        espece=p.espece,
                        recette=p.recette_id,
                        stade=p.stade,
                        prioritaire=p.prioritaire,
                        variete=p.variete,
                        date_semis=p.date_semis,
                        date_plantation=p.date_plantation,
                        notes=p.notes,
                    )
                )
            emplacements.append(emp)
        zones.append(
            _drop_none(
                dict(
                    id=z.id,
                    nom=z.nom,
                    jour_debut=z.jour_debut,
                    presence_autorisee=z.presence_autorisee,
                    cuve=z.cuve_id or False,
                    emplacements=emplacements,
                )
            )
        )

    actionneurs = [
        _drop_none(
            dict(
                id=a.id,
                zone=a.zone_id,
                type=a.type,
                noeud=a.noeud,
                commande=a.commande,
                duree_max_s=a.duree_max_s,
                puissance_w=a.puissance_w,
                ppfd_max=a.ppfd_max,
                debit_l_h=a.debit_l_h,
                debit_ml_min=a.debit_ml_min,
                **{k: v for k, v in (a.parametres or {}).items() if k in ACTIONNEUR_PARAMETRES},
            )
        )
        for a in session.scalars(select(m.Actionneur).order_by(m.Actionneur.id))
    ]

    return dict(
        nom=serre.nom,
        fuseau=serre.fuseau,
        tarif_kwh=serre.tarif_kwh,
        recettes={
            r.id: {"espece": r.espece, "stades": r.stades}
            for r in session.scalars(select(m.Recette).order_by(m.Recette.id))
        },
        zones=zones,
        cuves=[
            _drop_none(dict(id=c.id, volume_l=c.volume_l))
            for c in session.scalars(select(m.Cuve).order_by(m.Cuve.id))
        ],
        actionneurs=actionneurs,
        capteurs=_capteurs(session),
        cameras=_cameras(session),
        **{k: v for k, v in params.items() if k in PARAMETRES},
    )


def _capteurs(session: Session) -> list[dict]:
    """Declared devices, regrouped from their channels; channels registered by the
    ingestion alone (no `materiel`) are not part of the configuration."""
    rows = session.scalars(
        select(m.Capteur).where(m.Capteur.materiel.is_not(None)).order_by(m.Capteur.id)
    ).all()
    zone_emps = {
        z: set(session.scalars(select(m.Emplacement.id).where(m.Emplacement.zone_id == z)))
        for z in {r.zone for r in rows}
    }
    devices: dict[str, list[m.Capteur]] = {}
    for r in rows:
        devices.setdefault(r.materiel, []).append(r)
    out = []
    for dev_id in sorted(devices):
        chans = devices[dev_id]
        c = chans[0]
        links = set(
            session.scalars(
                select(m.CapteurEmplacement.emplacement_id).where(
                    m.CapteurEmplacement.capteur_id == c.id
                )
            )
        )
        couverts = "*" if c.emplacement is not None or links == zone_emps[c.zone] else sorted(links)
        plage = (c.plage_min, c.plage_max) if c.plage_min is not None else None
        out.append(
            _drop_none(
                dict(
                    id=dev_id,
                    modele=c.modele,
                    noeud=c.noeud,
                    zone=c.zone,
                    mesures=sorted((ch.type for ch in chans), key=_MESURES.index),
                    emplacement=c.emplacement,
                    cuve=c.cuve_id is not None,
                    emplacements_couverts=couverts,
                    etalonnage=c.etalonnage,
                    plage=plage,
                )
            )
        )
    return out


def _cameras(session: Session) -> list[dict]:
    out = []
    for cam in session.scalars(select(m.Camera).order_by(m.Camera.id)):
        regions = session.scalars(
            select(m.CameraRegion)
            .where(m.CameraRegion.camera_id == cam.id)
            .order_by(m.CameraRegion.emplacement_id)
        ).all()
        out.append(
            dict(
                id=cam.id,
                zone=cam.zone_id,
                emplacements_visibles=[r.emplacement_id for r in regions],
                regions={r.emplacement_id: r.bbox for r in regions if r.bbox is not None},
            )
        )
    return out


def content_hash(cfg: SerreCfg) -> str:
    content = cfg.model_dump(mode="json", exclude={"config_version"})
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def export(session: Session, now: datetime | None = None) -> Export:
    """Validate the configuration of the database and version it. The caller commits."""
    raw = build_config(session)
    cfg = SerreCfg.model_validate({**raw, "config_version": 0})
    gh = Greenhouse(cfg, cfg.load_recipes())  # unknown recipe / stage: ValueError, KeyError
    sha = content_hash(cfg)
    last = session.scalars(
        select(m.ConfigExport).order_by(m.ConfigExport.version.desc()).limit(1)
    ).first()
    serre = session.scalars(select(m.Serre)).first()
    if last is not None and last.sha256 == sha:
        version, changed = last.version, False
    else:
        top = session.scalar(select(func.max(m.ConfigExport.version))) or 0
        version, changed = max(top, serre.config_version) + 1, True
    cfg = cfg.model_copy(update={"config_version": version})
    if changed:
        session.add(
            m.ConfigExport(
                version=version,
                ts=now or datetime.now(UTC),
                sha256=sha,
                contenu=cfg.model_dump(mode="json"),
            )
        )
        serre.config_version = version
        session.flush()
    return Export(version, cfg, changed, gh.warnings)


class _Dumper(yaml.SafeDumper):
    """Ranges, bboxes and short lists of names on one line, like the hand-written file."""


def _list(dumper: yaml.SafeDumper, data: list):
    flow = all(not isinstance(v, dict | list) for v in data)
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=flow)


_Dumper.add_representer(list, _list)


def render(cfg: SerreCfg) -> str:
    data = cfg.model_dump(mode="json", exclude_defaults=True)
    data = {"config_version": cfg.config_version, **data}
    header = (
        f"# serre.yaml v{cfg.config_version}, généré par python -m backend.config.export "
        "(docs/09 §8) :\n# modifier la base (seed, puis UI en G2), pas ce fichier.\n"
    )
    return header + yaml.dump(data, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=100)


def install(text: str, path: Path) -> None:
    """Atomic replacement: the controller's ConfigWatcher never reads a partial file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", help="URL SQLAlchemy (défaut : $SERREIA_DB ou le compose)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="dossier des versions")
    parser.add_argument("--install", type=Path, help="copie locale, ex. edge/controller/serre.yaml")
    parser.add_argument("--rsync", help="destination rsync, ex. pi@serre.local:SerreIA/edge/…")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    engine = make_engine(args.db)
    init_db(engine)
    with make_sessions(engine).begin() as session:
        exp = export(session)  # Greenhouse logs the consistency warnings
    deliver(exp, args.out, args.install, args.rsync)


def deliver(
    exp: Export, out: Path = DEFAULT_OUT, install_to: Path | None = None, rsync: str | None = None
) -> Path:
    """Write the version in `out`, then install it locally and/or copy it with rsync."""
    text = exp.yaml()
    path = Path(out) / f"serre_config_v{exp.version}.yaml"
    install(text, path)
    log.info(
        "configuration v%d %s : %s",
        exp.version,
        "nouvelle" if exp.changed else "inchangée",
        path,
    )
    if install_to:
        install(text, install_to)
        log.info("installée : %s", install_to)
    if rsync:
        subprocess.run(["rsync", "-a", str(path), rsync], check=True)
        log.info("copiée : %s", rsync)
    return path


if __name__ == "__main__":
    main()
