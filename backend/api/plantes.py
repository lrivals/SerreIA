"""Plants (docs/09 §1, docs/12 §2.1): record, move, history.

A plant is on at most one emplacement at a time (`affectation` with `fin` None); moving
it closes the current assignment and opens a new one, so that the history of the
emplacements (measurements, images, decisions) stays attributed to the right plant.
"""

import re
from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select

from common.mqtt.schemas import SanteEtat

from ..db import models as m
from ..db.seed import _assign
from ..db.session import utc
from .crud import absent, get, patch, row
from .deps import Db, Now
from .serres import _vision

router = APIRouter(prefix="/plantes", tags=["plantes"])

MAX_VISION = 50


class PlanteIn(BaseModel):
    id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    espece: str = Field(min_length=1, max_length=64)
    variete: str | None = None
    date_semis: date | None = None
    date_plantation: date | None = None
    stade: str = Field(min_length=1, max_length=16)
    recette_id: str | None = None
    prioritaire: bool = False
    notes: str | None = None
    emplacement: str | None = None  # placed at once on this emplacement


class PlantePatch(BaseModel):
    espece: str | None = Field(default=None, min_length=1, max_length=64)
    variete: str | None = None
    date_semis: date | None = None
    date_plantation: date | None = None
    stade: str | None = Field(default=None, min_length=1, max_length=16)
    recette_id: str | None = None
    etat_sante: SanteEtat | None = None
    prioritaire: bool | None = None
    notes: str | None = None


class Deplacer(BaseModel):
    emplacement: str | None  # None: the plant leaves the greenhouse (assignment closed)


def _check_stage(s, recette_id: str | None, stade: str) -> None:
    if recette_id is None:
        return
    r = get(s, m.Recette, recette_id, "recette")
    if stade not in r.stades:
        raise HTTPException(
            422, f"stade {stade!r} absent de la recette {recette_id} ({', '.join(r.stades)})"
        )


def _current(s, plante_id: str) -> m.Affectation | None:
    return s.scalars(
        select(m.Affectation).where(
            m.Affectation.plante_id == plante_id, m.Affectation.fin.is_(None)
        )
    ).first()


def _plant(s, p: m.Plante) -> dict:
    a = _current(s, p.id)
    return dict(row(p), emplacement=a.emplacement_id if a else None)


def _place(s, plante_id: str, emplacement: str | None, now) -> None:
    if emplacement is not None:
        get(s, m.Emplacement, emplacement, "emplacement")
        other = s.scalars(
            select(m.Affectation).where(
                m.Affectation.emplacement_id == emplacement, m.Affectation.fin.is_(None)
            )
        ).first()
        if other is not None and other.plante_id != plante_id:
            raise HTTPException(409, f"{emplacement} est occupé par {other.plante_id}")
        _assign(s, emplacement, plante_id, now)
        return
    current = _current(s, plante_id)
    if current is not None:
        current.fin = now
        s.flush()


@router.get("")
def list_plantes(s: Db, actives: bool = False, zone: str | None = None) -> list[dict]:
    """`actives`: only the plants on an emplacement; `zone`: those of a zone."""
    places = {
        a.plante_id: a.emplacement_id
        for a in s.scalars(select(m.Affectation).where(m.Affectation.fin.is_(None)))
    }
    out = []
    for p in s.scalars(select(m.Plante).order_by(m.Plante.id)):
        emp = places.get(p.id)
        if (actives or zone) and emp is None:
            continue
        if zone and not emp.startswith(f"{zone}-"):
            continue
        out.append(dict(row(p), emplacement=emp))
    return out


def _new_id(s, espece: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", espece.lower()).strip("-") or "plante"
    n = 1
    while s.get(m.Plante, f"{base}-{n}") is not None:
        n += 1
    return f"{base}-{n}"


@router.post("", status_code=201)
def create_plante(body: PlanteIn, s: Db, now: Now) -> dict:
    pid = body.id or _new_id(s, body.espece)
    absent(s, m.Plante, pid, "plante")
    _check_stage(s, body.recette_id, body.stade)
    p = m.Plante(id=pid, etat_sante="sain", **body.model_dump(exclude={"id", "emplacement"}))
    s.add(p)
    s.flush()
    if body.emplacement is not None:
        _place(s, pid, body.emplacement, now)
    return _plant(s, p)


@router.get("/{pid}")
def get_plante(pid: str, s: Db) -> dict:
    return _plant(s, get(s, m.Plante, pid, "plante"))


@router.patch("/{pid}")
def update_plante(pid: str, body: PlantePatch, s: Db) -> dict:
    p = get(s, m.Plante, pid, "plante")
    fields = body.model_fields_set
    if fields & {"recette_id", "stade"}:
        _check_stage(s, body.recette_id if "recette_id" in fields else p.recette_id,
                     body.stade or p.stade)  # fmt: skip
    patch(p, body)
    s.flush()
    return _plant(s, p)


@router.post("/{pid}/deplacer")
def move_plante(pid: str, body: Deplacer, s: Db, now: Now) -> dict:
    get(s, m.Plante, pid, "plante")
    _place(s, pid, body.emplacement, now)
    return _plant(s, s.get(m.Plante, pid))


@router.get("/{pid}/historique")
def plante_history(pid: str, s: Db) -> dict:
    """Assignments, health actions (`plante:<emplacement>` targets) and classifications of
    the plant, each restricted to the periods it spent on the emplacement."""
    p = get(s, m.Plante, pid, "plante")
    affs = list(
        s.scalars(
            select(m.Affectation)
            .where(m.Affectation.plante_id == pid)
            .order_by(m.Affectation.debut)
        )
    )

    actions, vision = [], []
    if affs:
        act_q = select(m.Action).where(
            or_(*[(m.Action.cible == f"plante:{a.emplacement_id}") & _period(m.Action.ts_debut, a)
                  for a in affs])
        )  # fmt: skip
        actions = [
            dict(ts=utc(x.ts_debut), label=x.label, resultat=x.resultat, decision_id=x.decision_id)
            for x in s.scalars(act_q.order_by(m.Action.ts_debut))
        ]
        vis_q = select(m.VisionResultat).where(
            or_(*[(m.VisionResultat.emplacement_id == a.emplacement_id)
                  & _period(m.VisionResultat.ts, a) for a in affs])
        )  # fmt: skip
        vision = [
            _vision(v)
            for v in s.scalars(vis_q.order_by(m.VisionResultat.ts.desc()).limit(MAX_VISION))
        ]
    return dict(
        plante=_plant(s, p),
        affectations=[
            dict(
                emplacement=a.emplacement_id, debut=utc(a.debut), fin=utc(a.fin) if a.fin else None
            )
            for a in affs
        ],
        actions=actions,
        vision=vision,
    )


def _period(col, a: m.Affectation):
    return and_(col >= a.debut, col < a.fin) if a.fin is not None else col >= a.debut
