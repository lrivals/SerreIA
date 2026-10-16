"""Load the controller configuration (`serre.yaml` + recipes) into the database.

    python -m backend.db.seed                                  # edge/controller/serre.yaml
    python -m backend.db.seed --config serre.yaml --db sqlite:///serreia.db

Idempotent: rows are upserted by id. A plant that changed emplacement, or an emplacement
emptied in the configuration, closes its assignment and opens the new one (docs/09 §1).
Until the UI exists (G2), serre.yaml is the source of truth of the configuration.
"""

import argparse
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from edge.controller.config import DEFAULT_CONFIG, Greenhouse, load_greenhouse

from .models import Actionneur, Affectation, Cuve, Emplacement, Plante, Recette, Serre, Zone
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
        )
    )
    for rid, recipe in gh.recipes.items():
        stades = recipe.model_dump(mode="json", exclude_none=True)["stades"]
        session.merge(Recette(id=rid, espece=recipe.espece, stades=stades))
    for z in cfg.zones:
        cuve_id = f"cuve-{z.id}" if z.cuve else None
        if cuve_id:
            session.merge(Cuve(id=cuve_id, serre_id=sid))
        session.merge(
            Zone(
                id=z.id,
                serre_id=sid,
                nom=z.nom,
                cuve_id=cuve_id,
                jour_debut=z.jour_debut.strftime("%H:%M"),
            )
        )
        session.flush()
        for e in z.emplacements:
            code = e.id.removeprefix(f"{z.id}-")
            rangee, colonne = _grid(code)
            session.merge(
                Emplacement(
                    id=e.id,
                    zone_id=z.id,
                    code=code,
                    mode_culture=e.mode_culture,
                    rangee=rangee,
                    colonne=colonne,
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
                        stade=p.stade,
                        recette_id=p.recette,
                        prioritaire=p.prioritaire,
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
                ppfd_max=a.ppfd_max,
                duree_max_s=a.duree_max_s,
            )
        )
    session.flush()
    return sid


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
        sid = seed(session, gh)
    log.info("serre %s : configuration v%d chargée depuis %s", sid, gh.version, args.config)


if __name__ == "__main__":
    main()
