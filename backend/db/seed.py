"""Load the controller configuration (`serre.yaml` + recipes) into the database.

    python -m backend.db.seed                                  # edge/controller/serre.yaml
    python -m backend.db.seed --config serre.yaml --db sqlite:///serreia.db

Idempotent: rows are upserted by id. A plant that changed emplacement, or an emplacement
emptied in the configuration, closes its assignment and opens the new one (docs/09 §1).
Declared sensors give one `capteur` row per channel (node × measure × emplacement), the
id the ingestion matches; cameras give one `camera_region` per visible emplacement.
Until the UI exists (G2), serre.yaml is the source of truth of the configuration.
"""

import argparse
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from edge.controller.config import DEFAULT_CONFIG, Greenhouse, ZoneCfg, load_greenhouse

from .models import (
    Actionneur,
    Affectation,
    Camera,
    CameraRegion,
    Capteur,
    CapteurEmplacement,
    Contenant,
    Cuve,
    Emplacement,
    Plante,
    Recette,
    Serre,
    Zone,
)
from .session import init_db, make_engine, make_sessions

log = logging.getLogger(__name__)


def serre_id(nom: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", nom.lower()).strip("-") or "serre"


def seed(session: Session, gh: Greenhouse, now: datetime | None = None) -> str:
    """Upsert the configuration of `gh`; returns the serre id. The caller commits."""
    now = now or datetime.now(UTC)
    cfg = gh.cfg
    sid = serre_id(cfg.nom)
    session.merge(
        Serre(
            id=sid,
            nom=cfg.nom,
            fuseau=cfg.fuseau,
            tarif_kwh=cfg.tarif_kwh,
            lux_vers_ppfd=cfg.lumiere.lux_vers_ppfd,
            config_version=cfg.config_version,
            parametres=cfg.model_dump(mode="json", include=set(PARAMETRES)),
        )
    )
    for rid, recipe in gh.recipes.items():
        stades = recipe.model_dump(mode="json", exclude_none=True)["stades"]
        session.merge(Recette(id=rid, espece=recipe.espece, stades=stades))
    volumes = {c.id: c.volume_l for c in cfg.cuves}
    for z in cfg.zones:
        cuve_id = z.cuve_id
        if cuve_id:
            session.merge(Cuve(id=cuve_id, serre_id=sid, volume_l=volumes.get(cuve_id)))
        session.merge(
            Zone(
                id=z.id,
                serre_id=sid,
                nom=z.nom,
                cuve_id=cuve_id,
                jour_debut=z.jour_debut.strftime("%H:%M"),
                presence_autorisee=[p.model_dump(mode="json") for p in z.presence_autorisee],
            )
        )
        session.flush()
        for e in z.emplacements:
            code = e.id.removeprefix(f"{z.id}-")
            rangee, colonne = _grid(code)
            existing_emp = session.get(Emplacement, e.id)
            session.merge(
                Emplacement(
                    id=e.id,
                    zone_id=z.id,
                    code=code,
                    mode_culture=e.mode_culture,
                    rangee=rangee,
                    colonne=colonne,
                    contenant_id=_contenant(
                        session, e.contenant, existing_emp.contenant_id if existing_emp else None
                    ),
                )
            )
            session.flush()
            if e.plante is not None:
                p = e.plante
                existing = session.get(Plante, p.id)
                session.merge(
                    Plante(
                        id=p.id,
                        espece=p.espece,
                        variete=p.variete,
                        date_semis=p.date_semis,
                        date_plantation=p.date_plantation,
                        stade=p.stade,
                        recette_id=p.recette,
                        prioritaire=p.prioritaire,
                        notes=p.notes,
                        etat_sante=existing.etat_sante if existing else "sain",
                    )
                )
                session.flush()
            _assign(session, e.id, e.plante.id if e.plante else None, now)
    for a in cfg.actionneurs:
        session.merge(
            Actionneur(
                id=a.id,
                zone_id=a.zone,
                type=a.type.value,
                noeud=a.noeud,
                commande=a.commande,
                puissance_w=a.puissance_w,
                debit_l_h=a.debit_l_h,
                debit_ml_min=a.debit_ml_min,
                ppfd_max=a.ppfd_max,
                duree_max_s=a.duree_max_s,
                parametres=a.model_dump(mode="json", include=set(ACTIONNEUR_PARAMETRES)),
            )
        )
    session.flush()
    zones = {z.id: z for z in cfg.zones}
    for c in cfg.capteurs:
        _capteur(session, c, zones[c.zone])
    for cam in cfg.cameras:
        session.merge(Camera(id=cam.id, zone_id=cam.zone))
        session.flush()
        session.execute(delete(CameraRegion).where(CameraRegion.camera_id == cam.id))
        for e in cam.emplacements_visibles:
            bbox = cam.regions.get(e)
            session.add(
                CameraRegion(camera_id=cam.id, emplacement_id=e, bbox=list(bbox) if bbox else None)
            )
    session.flush()
    return sid


# serre.yaml fields stored as JSON (no column of their own), given back by the export.
PARAMETRES = ("hysteresis", "securite", "risque", "lumiere", "prevision")
ACTIONNEUR_PARAMETRES = ("duree_s", "impulsion_s", "melange_s", "delai_min_s", "marche_min_s")


def _contenant(session: Session, cfg, current: int | None) -> int | None:
    """Container of an emplacement: updated in place (idempotent seed), created if new."""
    if cfg is None:
        return None
    row = session.get(Contenant, current) if current is not None else None
    if row is None:
        row = Contenant()
        session.add(row)
    row.type, row.volume_l, row.materiau, row.drainage = (
        cfg.type,
        cfg.volume_l,
        cfg.materiau,
        cfg.drainage,
    )
    session.flush()
    return row.id


def _capteur(session: Session, c, zone: ZoneCfg) -> None:
    """One `capteur` row per channel of a declared device, linked to the emplacements it
    covers. Fields the ingestion does not know (model, calibration…) are overwritten."""
    couverts = c.couverts(zone)
    for cid, mesure in c.canaux():
        session.merge(
            Capteur(
                id=cid,
                materiel=c.id,
                noeud=c.noeud,
                zone=c.zone,
                type=mesure.value,
                emplacement=c.emplacement,
                modele=c.modele,
                cuve_id=zone.cuve_id if c.cuve else None,
                etalonnage=c.model_dump(mode="json")["etalonnage"],
                plage_min=c.plage[0] if c.plage else None,
                plage_max=c.plage[1] if c.plage else None,
            )
        )
        session.flush()
        session.execute(delete(CapteurEmplacement).where(CapteurEmplacement.capteur_id == cid))
        for e in couverts:
            session.add(CapteurEmplacement(capteur_id=cid, emplacement_id=e))
    session.flush()


def _grid(code: str) -> tuple[int | None, int | None]:
    """ "A1" -> (1, 1), "B12" -> (2, 12); other codes have no grid position."""
    m = re.fullmatch(r"([A-Z])(\d+)", code)
    return (ord(m[1]) - ord("A") + 1, int(m[2])) if m else (None, None)


def _assign(session: Session, emplacement: str, plante: str | None, now: datetime) -> None:
    """At most one active plant per emplacement; a plant is active on one emplacement."""
    current = session.scalars(
        select(Affectation).where(
            Affectation.emplacement_id == emplacement, Affectation.fin.is_(None)
        )
    ).first()
    if current is not None and current.plante_id == plante:
        return
    if current is not None:
        current.fin = now
    if plante is None:
        session.flush()
        return
    elsewhere = session.scalars(
        select(Affectation).where(Affectation.plante_id == plante, Affectation.fin.is_(None))
    )
    for a in elsewhere:  # the plant was moved
        a.fin = now
    session.flush()
    session.add(Affectation(plante_id=plante, emplacement_id=emplacement, debut=now))
    session.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--db", help="URL SQLAlchemy (défaut : $SERREIA_DB ou le compose)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    engine = make_engine(args.db)
    init_db(engine)
    gh = load_greenhouse(args.config)
    with make_sessions(engine).begin() as session:
        sid = seed(session, gh)  # load_greenhouse logged the consistency warnings
    log.info("serre %s : configuration v%d chargée depuis %s", sid, gh.version, args.config)


if __name__ == "__main__":
    main()
