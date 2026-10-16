"""Decision log (docs/10 §2, docs/12 §5): list, record with its evidence and actions,
validation or rejection of a `proposee` decision."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import models as m
from ..db.session import utc
from ..traceability import decision_message, publish_decision, reconcile
from .deps import Db, Now, Pub

router = APIRouter(prefix="/decisions", tags=["decisions"])


class Reponse(BaseModel):
    utilisateur: str = "ui"
    commentaire: str | None = None


def _summary(d: m.Decision) -> dict:
    return dict(
        id=d.id,
        ts=utc(d.ts),
        zone=d.zone,
        emplacements=d.emplacements,
        niveau=d.niveau,
        origine=d.origine,
        regle={"id": d.regle_id, "version": d.regle_version},
        type=d.type,
        statut=d.statut,
        explication=d.explication,
        actions=d.actions,
        expire=utc(d.expire) if d.expire else None,
    )


@router.get("")
def list_decisions(
    s: Db,
    zone: str | None = None,
    debut: datetime | None = None,
    fin: datetime | None = None,
    type: str | None = None,
    statut: str | None = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 200,
) -> list[dict]:
    q = select(m.Decision)
    if zone:
        q = q.where(m.Decision.zone == zone)
    if debut:
        q = q.where(m.Decision.ts >= utc(debut))
    if fin:
        q = q.where(m.Decision.ts < utc(fin))
    if type:
        q = q.where(m.Decision.type == type)
    if statut:
        q = q.where(m.Decision.statut == statut)
    return [_summary(d) for d in s.scalars(q.order_by(m.Decision.ts.desc()).limit(limit))]


@router.get("/{decision_id}")
def get_decision(decision_id: str, s: Db) -> dict:
    """Record of a decision (docs/12, "fiche décision"): evidence, orders, actions and the
    commands that point to it."""
    d = s.get(m.Decision, decision_id)
    if d is None:
        raise HTTPException(404, f"décision inconnue {decision_id}")
    acts = s.scalars(select(m.Action).where(m.Action.decision_id == d.id).order_by(m.Action.id))
    cmds = s.scalars(
        select(m.Commande).where(m.Commande.decision_id == d.id).order_by(m.Commande.ts)
    )
    return dict(
        _summary(d),
        config_version=d.config_version,
        preuves=d.preuves,
        ordres=d.ordres or [],
        actions_detail=[
            dict(
                id=a.id,
                cible=a.cible,
                label=a.label,
                resultat=a.resultat,
                commande=a.commande,
                ts_debut=utc(a.ts_debut),
                ts_fin=utc(a.ts_fin) if a.ts_fin else None,
            )
            for a in acts
        ],
        commandes=[
            dict(
                ts=utc(c.ts),
                actionneur=c.actionneur,
                action=c.action,
                valeur=c.valeur,
                duree_s=c.duree_s,
                source=c.source,
                raison=c.raison,
            )
            for c in cmds
        ],  # fmt: skip
    )


def _answer(s: Session, decision_id: str, now: datetime) -> m.Decision:
    d = s.get(m.Decision, decision_id)
    if d is None:
        raise HTTPException(404, f"décision inconnue {decision_id}")
    if d.statut != "proposee":
        raise HTTPException(409, f"{decision_id} est « {d.statut} », pas « proposee »")
    if d.expire is not None and utc(d.expire) <= utc(now):  # `reconcile` will mark it
        raise HTTPException(409, f"{decision_id} a expiré le {utc(d.expire).isoformat()}")
    return d


def _note(r: Reponse, verbe: str) -> str:
    note = f" [{verbe} par ui:{r.utilisateur}"
    return note + (f" : {r.commentaire}]" if r.commentaire else "]")


@router.post("/{decision_id}/valider")
def validate(decision_id: str, r: Reponse, s: Db, now: Now, pub: Pub) -> dict:
    """The controller runs the orders of the decision through safety.py, then publishes it
    again (`executee` or `bloquee_securite`) with its commands."""
    d = _answer(s, decision_id, now)
    d.statut, d.explication = "validee", d.explication + _note(r, "validée")
    publish_decision(pub, decision_message(d))
    return _summary(d)


@router.post("/{decision_id}/rejeter")
def reject(decision_id: str, r: Reponse, s: Db, now: Now, pub: Pub) -> dict:
    d = _answer(s, decision_id, now)
    d.statut, d.explication = "rejetee", d.explication + _note(r, "rejetée")
    s.flush()
    reconcile(s, now)
    publish_decision(pub, decision_message(d))
    return _summary(d)
