"""Greenhouse structure (docs/09 §1, docs/12 §2.1): serres, zones, emplacements, tanks,
containers and recipes, and the plan of a zone for the builder.

Changes only touch the database: the controller sees them once a configuration is
published (`POST /api/config/publier`, docs/09 §8).
"""

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from edge.controller.config import ModeCulture
from edge.controller.recipes import Recipe

from ..db import models as m
from ..db.seed import _grid, serre_id
from ..db.session import utc
from .crud import Disposition, absent, disposition, get, in_use, patch, row
from .deps import Db

router = APIRouter(tags=["serre"])

ZONE_ID = r"^z\d+$"
CODE = r"^[A-Za-z0-9]{1,12}$"
ID = r"^[a-z0-9][a-z0-9_-]{0,63}$"


# --- serres --------------------------------------------------------------------------


class SerreIn(BaseModel):
    nom: str = Field(min_length=1, max_length=128)
    fuseau: str = "Europe/Paris"
    tarif_kwh: float | None = Field(default=None, ge=0)
    lux_vers_ppfd: float = Field(default=0.0185, gt=0)


class SerrePatch(BaseModel):
    nom: str | None = Field(default=None, min_length=1, max_length=128)
    fuseau: str | None = None
    tarif_kwh: float | None = Field(default=None, ge=0)
    lux_vers_ppfd: float | None = Field(default=None, gt=0)
    parametres: dict | None = None


@router.get("/serres")
def list_serres(s: Db) -> list[dict]:
    return [row(x) for x in s.scalars(select(m.Serre).order_by(m.Serre.id))]


@router.post("/serres", status_code=201)
def create_serre(body: SerreIn, s: Db) -> dict:
    sid = serre_id(body.nom)
    absent(s, m.Serre, sid, "serre")
    x = m.Serre(id=sid, config_version=0, **body.model_dump())
    s.add(x)
    s.flush()
    return row(x)


@router.get("/serres/{sid}")
def get_serre(sid: str, s: Db) -> dict:
    return row(get(s, m.Serre, sid, "serre"))


@router.patch("/serres/{sid}")
def update_serre(sid: str, body: SerrePatch, s: Db) -> dict:
    x = get(s, m.Serre, sid, "serre")
    patch(x, body)
    s.flush()
    return row(x)


@router.delete("/serres/{sid}", status_code=204)
def delete_serre(sid: str, s: Db) -> None:
    x = get(s, m.Serre, sid, "serre")
    if s.scalar(select(func.count()).where(m.Zone.serre_id == sid)):
        raise in_use(f"la serre {sid}", "des zones")
    s.delete(x)


def _serre(s, sid: str | None) -> str:
    if sid is not None:
        return get(s, m.Serre, sid, "serre").id
    first = s.scalars(select(m.Serre).order_by(m.Serre.id)).first()
    if first is None:
        raise HTTPException(409, "aucune serre : en créer une d'abord")
    return first.id


# --- cuves ---------------------------------------------------------------------------


class CuveIn(BaseModel):
    id: str = Field(pattern=ID)
    serre_id: str | None = None
    volume_l: float | None = Field(default=None, gt=0)
    disposition: Disposition | None = None


class CuvePatch(BaseModel):
    volume_l: float | None = Field(default=None, gt=0)
    disposition: Disposition | None = None


@router.get("/cuves")
def list_cuves(s: Db) -> list[dict]:
    return [row(x) for x in s.scalars(select(m.Cuve).order_by(m.Cuve.id))]


@router.post("/cuves", status_code=201)
def create_cuve(body: CuveIn, s: Db) -> dict:
    absent(s, m.Cuve, body.id, "cuve")
    x = m.Cuve(
        id=body.id,
        serre_id=_serre(s, body.serre_id),
        volume_l=body.volume_l,
        disposition=disposition(body.disposition),
    )
    s.add(x)
    s.flush()
    return row(x)


@router.get("/cuves/{cid}")
def get_cuve(cid: str, s: Db) -> dict:
    return row(get(s, m.Cuve, cid, "cuve"))


@router.patch("/cuves/{cid}")
def update_cuve(cid: str, body: CuvePatch, s: Db) -> dict:
    x = get(s, m.Cuve, cid, "cuve")
    patch(x, body, skip=("disposition",))
    if "disposition" in body.model_fields_set:
        x.disposition = disposition(body.disposition)
    s.flush()
    return row(x)


@router.delete("/cuves/{cid}", status_code=204)
def delete_cuve(cid: str, s: Db) -> None:
    x = get(s, m.Cuve, cid, "cuve")
    if s.scalar(select(func.count()).where(m.Zone.cuve_id == cid)):
        raise in_use(f"la cuve {cid}", "une zone")
    s.delete(x)


# --- zones ---------------------------------------------------------------------------


class Periode(BaseModel):
    debut: str = Field(pattern=r"^\d{2}:\d{2}$")
    fin: str = Field(pattern=r"^\d{2}:\d{2}$")


class ZoneIn(BaseModel):
    id: str | None = Field(default=None, pattern=ZONE_ID)  # default: next z<n>
    serre_id: str | None = None
    nom: str = ""
    cuve_id: str | None = None
    jour_debut: str = Field(default="06:00", pattern=r"^\d{2}:\d{2}$")
    presence_autorisee: list[Periode] = []
    disposition: Disposition | None = None


class ZonePatch(BaseModel):
    nom: str | None = None
    cuve_id: str | None = None
    jour_debut: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    presence_autorisee: list[Periode] | None = None
    disposition: Disposition | None = None


@router.get("/zones")
def list_zones(s: Db) -> list[dict]:
    counts = dict(
        s.execute(select(m.Emplacement.zone_id, func.count()).group_by(m.Emplacement.zone_id)).all()
    )
    return [
        dict(row(z), n_emplacements=counts.get(z.id, 0))
        for z in s.scalars(select(m.Zone).order_by(m.Zone.id))
    ]


def _next_zone(s) -> str:
    nums = [int(z[1:]) for z in s.scalars(select(m.Zone.id)) if re.fullmatch(ZONE_ID, z)]
    return f"z{max(nums, default=0) + 1}"


@router.post("/zones", status_code=201)
def create_zone(body: ZoneIn, s: Db) -> dict:
    zid = body.id or _next_zone(s)
    absent(s, m.Zone, zid, "zone")
    if body.cuve_id is not None:
        get(s, m.Cuve, body.cuve_id, "cuve")
    z = m.Zone(
        id=zid,
        serre_id=_serre(s, body.serre_id),
        nom=body.nom,
        cuve_id=body.cuve_id,
        jour_debut=body.jour_debut,
        presence_autorisee=[p.model_dump() for p in body.presence_autorisee],
        disposition=disposition(body.disposition),
    )
    s.add(z)
    s.flush()
    return row(z)


@router.get("/zones/{zid}")
def get_zone(zid: str, s: Db) -> dict:
    return row(get(s, m.Zone, zid, "zone"))


@router.patch("/zones/{zid}")
def update_zone(zid: str, body: ZonePatch, s: Db) -> dict:
    z = get(s, m.Zone, zid, "zone")
    if body.cuve_id is not None:
        get(s, m.Cuve, body.cuve_id, "cuve")
    patch(z, body, skip=("presence_autorisee", "disposition"))
    if "disposition" in body.model_fields_set:
        z.disposition = disposition(body.disposition)
    if body.presence_autorisee is not None:
        z.presence_autorisee = [p.model_dump() for p in body.presence_autorisee]
    s.flush()
    return row(z)


@router.delete("/zones/{zid}", status_code=204)
def delete_zone(zid: str, s: Db) -> None:
    z = get(s, m.Zone, zid, "zone")
    for model, col, what in (
        (m.Emplacement, m.Emplacement.zone_id, "des emplacements"),
        (m.Actionneur, m.Actionneur.zone_id, "des actionneurs"),
        (m.Camera, m.Camera.zone_id, "des caméras"),
    ):
        if s.scalar(select(func.count()).select_from(model).where(col == zid)):
            raise in_use(f"la zone {zid}", what)
    s.delete(z)


@router.get("/zones/{zid}/plan")
def zone_plan(zid: str, s: Db) -> dict:
    """The builder's grid (docs/12 §2.1): emplacements with their current plant, container,
    sensors, cameras and last classification."""
    z = get(s, m.Zone, zid, "zone")
    emps = list(
        s.scalars(
            select(m.Emplacement).where(m.Emplacement.zone_id == zid).order_by(m.Emplacement.id)
        )
    )
    ids = [e.id for e in emps]
    active = {
        a.emplacement_id: a
        for a in s.scalars(
            select(m.Affectation).where(
                m.Affectation.fin.is_(None), m.Affectation.emplacement_id.in_(ids)
            )
        )
    }
    plants = {
        p.id: p
        for p in s.scalars(
            select(m.Plante).where(m.Plante.id.in_([a.plante_id for a in active.values()]))
        )
    }
    capteurs = list(s.scalars(select(m.Capteur).where(m.Capteur.zone == zid)))
    links: dict[str, set[str]] = {}
    for cid, eid in s.execute(
        select(m.CapteurEmplacement.capteur_id, m.CapteurEmplacement.emplacement_id).where(
            m.CapteurEmplacement.emplacement_id.in_(ids)
        )
    ):
        links.setdefault(eid, set()).add(cid)
    cameras = list(s.scalars(select(m.Camera).where(m.Camera.zone_id == zid).order_by(m.Camera.id)))
    regions = list(
        s.scalars(
            select(m.CameraRegion).where(m.CameraRegion.camera_id.in_([c.id for c in cameras]))
        )
    )
    out = []
    for e in emps:
        a = active.get(e.id)
        p = plants.get(a.plante_id) if a else None
        c = s.get(m.Contenant, e.contenant_id) if e.contenant_id else None
        devices = sorted(
            {x.materiel or x.id for x in capteurs
             if x.emplacement == e.id or x.id in links.get(e.id, set())}
        )  # fmt: skip
        v = s.scalars(
            select(m.VisionResultat)
            .where(m.VisionResultat.emplacement_id == e.id)
            .order_by(m.VisionResultat.ts.desc())
            .limit(1)
        ).first()
        out.append(
            dict(
                row(e),
                contenant=row(c) if c else None,
                plante=dict(row(p), depuis=utc(a.debut)) if p else None,
                capteurs=devices,
                cameras=[
                    dict(id=r.camera_id, region=r.bbox) for r in regions if r.emplacement_id == e.id
                ],
                vision=_vision(v) if v else None,
            )
        )
    return dict(
        zone=row(z),
        emplacements=out,
        cameras=[
            dict(id=c.id, emplacements=[r.emplacement_id for r in regions if r.camera_id == c.id])
            for c in cameras
        ],
    )


def _vision(v: m.VisionResultat) -> dict:
    return dict(
        ts=utc(v.ts),
        image_id=v.image_id,
        camera=v.camera,
        espece=v.espece,
        espece_conf=v.espece_conf,
        sante=v.sante,
        sante_conf=v.sante_conf,
        classe=v.classe,
        classe_conf=v.classe_conf,
        bbox=v.bbox,
    )


# --- contenants ----------------------------------------------------------------------


class ContenantIn(BaseModel):
    type: str = Field(min_length=1, max_length=32)
    volume_l: float | None = Field(default=None, gt=0)
    materiau: str | None = None
    drainage: bool | None = None


class ContenantPatch(BaseModel):
    type: str | None = Field(default=None, min_length=1, max_length=32)
    volume_l: float | None = Field(default=None, gt=0)
    materiau: str | None = None
    drainage: bool | None = None


@router.get("/contenants")
def list_contenants(s: Db) -> list[dict]:
    return [row(x) for x in s.scalars(select(m.Contenant).order_by(m.Contenant.id))]


@router.post("/contenants", status_code=201)
def create_contenant(body: ContenantIn, s: Db) -> dict:
    x = m.Contenant(**body.model_dump())
    s.add(x)
    s.flush()
    return row(x)


@router.patch("/contenants/{cid}")
def update_contenant(cid: int, body: ContenantPatch, s: Db) -> dict:
    x = get(s, m.Contenant, cid, "contenant")
    patch(x, body)
    s.flush()
    return row(x)


@router.delete("/contenants/{cid}", status_code=204)
def delete_contenant(cid: int, s: Db) -> None:
    x = get(s, m.Contenant, cid, "contenant")
    if s.scalar(select(func.count()).where(m.Emplacement.contenant_id == cid)):
        raise in_use(f"le contenant {cid}", "un emplacement")
    s.delete(x)


# --- emplacements --------------------------------------------------------------------


class EmplacementIn(BaseModel):
    zone_id: str = Field(pattern=ZONE_ID)
    code: str = Field(pattern=CODE)  # A1: row A, column 1
    mode_culture: ModeCulture
    rangee: int | None = Field(default=None, ge=1)
    colonne: int | None = Field(default=None, ge=1)
    contenant_id: int | None = None
    contenant: ContenantIn | None = None  # created with the emplacement
    disposition: Disposition | None = None

    @field_validator("code")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()


class EmplacementPatch(BaseModel):
    mode_culture: ModeCulture | None = None
    rangee: int | None = Field(default=None, ge=1)
    colonne: int | None = Field(default=None, ge=1)
    contenant_id: int | None = None
    contenant: ContenantIn | None = None
    disposition: Disposition | None = None


def _contenant(s, body) -> int | None:
    if body.contenant is not None:
        c = m.Contenant(**body.contenant.model_dump())
        s.add(c)
        s.flush()
        return c.id
    if body.contenant_id is not None:
        get(s, m.Contenant, body.contenant_id, "contenant")
    return body.contenant_id


@router.get("/emplacements")
def list_emplacements(s: Db, zone: str | None = None) -> list[dict]:
    q = select(m.Emplacement).order_by(m.Emplacement.id)
    if zone:
        q = q.where(m.Emplacement.zone_id == zone)
    return [row(e) for e in s.scalars(q)]


@router.post("/emplacements", status_code=201)
def create_emplacement(body: EmplacementIn, s: Db) -> dict:
    get(s, m.Zone, body.zone_id, "zone")
    eid = f"{body.zone_id}-{body.code}"
    absent(s, m.Emplacement, eid, "emplacement")
    rangee, colonne = _grid(body.code)
    e = m.Emplacement(
        id=eid,
        zone_id=body.zone_id,
        code=body.code,
        mode_culture=body.mode_culture,
        rangee=body.rangee or rangee,
        colonne=body.colonne or colonne,
        contenant_id=_contenant(s, body),
        disposition=disposition(body.disposition),
    )
    s.add(e)
    s.flush()
    return row(e)


@router.get("/emplacements/{eid}")
def get_emplacement(eid: str, s: Db) -> dict:
    return row(get(s, m.Emplacement, eid, "emplacement"))


@router.patch("/emplacements/{eid}")
def update_emplacement(eid: str, body: EmplacementPatch, s: Db) -> dict:
    e = get(s, m.Emplacement, eid, "emplacement")
    patch(e, body, skip=("contenant", "contenant_id", "disposition"))
    if "disposition" in body.model_fields_set:
        e.disposition = disposition(body.disposition)
    if "contenant" in body.model_fields_set or "contenant_id" in body.model_fields_set:
        e.contenant_id = _contenant(s, body)
    s.flush()
    return row(e)


@router.delete("/emplacements/{eid}", status_code=204)
def delete_emplacement(eid: str, s: Db) -> None:
    """Refused once a plant has been there: the history of the plants keeps it."""
    e = get(s, m.Emplacement, eid, "emplacement")
    if s.scalar(select(func.count()).where(m.Affectation.emplacement_id == eid)):
        raise in_use(f"l'emplacement {eid}", "l'historique des plantes")
    for model in (m.CameraRegion, m.CapteurEmplacement):
        for link in s.scalars(select(model).where(model.emplacement_id == eid)):
            s.delete(link)
    s.flush()
    s.delete(e)


# --- recettes ------------------------------------------------------------------------


class RecetteIn(BaseModel):
    id: str = Field(pattern=ID)
    espece: str = Field(min_length=1, max_length=64)
    stades: dict = Field(min_length=1)


class RecettePatch(BaseModel):
    espece: str | None = Field(default=None, min_length=1, max_length=64)
    stades: dict | None = None


def _check_recipe(espece: str, stades: dict) -> dict:
    try:
        r = Recipe.model_validate({"espece": espece, "stades": stades})
    except ValueError as e:
        raise HTTPException(422, f"recette invalide : {e}") from e
    return r.model_dump(mode="json", exclude_none=True)["stades"]


@router.get("/recettes")
def list_recettes(s: Db) -> list[dict]:
    return [row(r) for r in s.scalars(select(m.Recette).order_by(m.Recette.id))]


@router.post("/recettes", status_code=201)
def create_recette(body: RecetteIn, s: Db) -> dict:
    absent(s, m.Recette, body.id, "recette")
    r = m.Recette(id=body.id, espece=body.espece, stades=_check_recipe(body.espece, body.stades))
    s.add(r)
    s.flush()
    return row(r)


@router.get("/recettes/{rid}")
def get_recette(rid: str, s: Db) -> dict:
    return row(get(s, m.Recette, rid, "recette"))


@router.patch("/recettes/{rid}")
def update_recette(rid: str, body: RecettePatch, s: Db) -> dict:
    r = get(s, m.Recette, rid, "recette")
    espece, stades = body.espece or r.espece, body.stades or r.stades
    r.espece, r.stades = espece, _check_recipe(espece, stades)
    s.flush()
    return row(r)


@router.delete("/recettes/{rid}", status_code=204)
def delete_recette(rid: str, s: Db) -> None:
    r = get(s, m.Recette, rid, "recette")
    if s.scalar(select(func.count()).where(m.Plante.recette_id == rid)):
        raise in_use(f"la recette {rid}", "des plantes")
    s.delete(r)
