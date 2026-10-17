"""Alerts (docs/12 §2.3): list and acknowledgement."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from ..db import models as m
from ..db.session import utc
from .deps import Db

router = APIRouter(prefix="/alertes", tags=["alertes"])


def _alert(a: m.Alerte) -> dict:
    return dict(id=a.id, ts=utc(a.ts), zone=a.zone, niveau=a.niveau, message=a.message,
                source=a.source, acquittee=a.acquittee)  # fmt: skip


@router.get("")
def list_alertes(
    s: Db,
    actives: bool = False,
    zone: str | None = None,
    niveau: str | None = None,
    debut: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 200,
) -> list[dict]:
    """`actives`: not acknowledged yet."""
    q = select(m.Alerte)
    if actives:
        q = q.where(m.Alerte.acquittee.is_(False))
    if zone:
        q = q.where(m.Alerte.zone == zone)
    if niveau:
        q = q.where(m.Alerte.niveau == niveau)
    if debut:
        q = q.where(m.Alerte.ts >= utc(debut))
    return [_alert(a) for a in s.scalars(q.order_by(m.Alerte.ts.desc()).limit(limit))]


@router.post("/{alerte_id}/acquitter")
def acknowledge(alerte_id: str, s: Db) -> dict:
    rows = list(s.scalars(select(m.Alerte).where(m.Alerte.id == alerte_id)))
    if not rows:
        raise HTTPException(404, f"alerte inconnue {alerte_id}")
    for a in rows:
        a.acquittee = True
    s.flush()
    return _alert(rows[0])
