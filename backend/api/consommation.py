"""Consumption (docs/09 §5, docs/12 §2.4): energy, water, inputs and light, estimated from
the actuator states (`backend/consumption.py`) until a power meter is declared."""

from datetime import date
from typing import Literal

from fastapi import APIRouter
from sqlalchemy import select

from ..consumption import summary
from ..db import models as m
from .deps import Db, Now
from .mesures import zone_setpoints_db

router = APIRouter(tags=["consommation"])


@router.get("/consommation")
def consommation(
    s: Db,
    now: Now,
    zone: str | None = None,
    periode: Literal["jour", "semaine", "mois"] = "semaine",
    jour: date | None = None,
) -> dict:
    out = summary(s, periode, zone, jour, now)
    zones = [zone] if zone else list(s.scalars(select(m.Zone.id).order_by(m.Zone.id)))
    cibles = {}
    for z in zones:
        sp = zone_setpoints_db(s, z)
        cibles[z] = sp.dli_cible if sp is not None else None
    return dict(out, dli_cible=cibles, estime=True)
