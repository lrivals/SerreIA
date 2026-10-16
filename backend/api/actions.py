"""Action tree (docs/10 §6) and manual actions (docs/10 §5, type `manuelle`)."""

import uuid
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from common.mqtt import Actuator, Ordre
from common.mqtt.schemas import Decision

from ..db import models as m
from ..traceability import build_tree, publish_decision, stored_row
from .deps import Db, Now, Pub

router = APIRouter(prefix="/actions", tags=["actions"])


@router.get("/arbre")
def tree(
    s: Db,
    now: Now,
    zone: str | None = None,
    debut: datetime | None = None,
    fin: datetime | None = None,
) -> dict:
    """Greenhouse → zones → routines (aggregated) / exceptional / safety / manual →
    decisions → actions, over [debut, fin) (default: the last 24 h)."""
    fin = fin or now
    return build_tree(s, debut or fin - timedelta(hours=24), fin, zone)


class Manuelle(BaseModel):
    zone: str = Field(pattern=r"^z\d+$")
    actionneur: Actuator
    action: Literal["on", "off", "pwm"]
    valeur: float | None = None
    duree_s: float | None = None
    utilisateur: str = "ui"
    justification: str = Field(min_length=1)


@router.post("/manuelle")
def manual(a: Manuelle, s: Db, now: Now, pub: Pub) -> dict:
    """A manual order: a decision `manuelle`, born `validee`, that the controller runs
    through safety.py like any other (docs/10 §1: no command without a decision)."""
    if s.get(m.Zone, a.zone) is None:
        raise HTTPException(404, f"zone inconnue {a.zone}")
    try:
        ordre = Ordre(cible=f"actionneur:{a.actionneur}", action=a.action, valeur=a.valeur,
                      duree_s=a.duree_s, texte=a.justification)  # fmt: skip
    except ValueError as e:
        raise HTTPException(422, str(e).splitlines()[-1]) from e
    d = Decision(
        id=f"dec-{now:%Y%m%d-%H%M}-{a.zone}-ui{uuid.uuid4().hex[:6]}",
        ts=now,
        zone=a.zone,
        niveau="manuel",
        origine=f"ui:{a.utilisateur}",
        regle={"id": "manuel.ui", "version": 1},
        type="manuelle",
        explication=f"{a.justification} → {ordre.label()} (demande de {a.utilisateur})",
        actions=[f"proposee:{ordre.label()}"],
        ordres=[ordre],
        statut="validee",
    )
    s.merge(m.Decision(**stored_row(d)))
    publish_decision(pub, d)
    return d.model_dump(mode="json")
