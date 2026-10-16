"""Equipment (docs/12 §2.2): sensors (channels), actuators, cameras and their regions,
ESP32 nodes. A manual command goes through `POST /api/actions/manuelle` (decision
`manuelle`, run by the controller through safety.py), never from here.
"""

from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from common.mqtt import Actuator, SensorType
from edge.controller.config import capteur_id

from ..db import models as m
from ..db.session import utc
from .crud import absent, get, patch, row
from .deps import Db, Now
from .serres import ZONE_ID

router = APIRouter(tags=["equipements"])

# Days between two calibrations before the UI shows a reminder (docs/12 §2.2).
ETALONNAGE_JOURS = {SensorType.PH: 30, SensorType.EC: 60}
ETALONNAGE_DEFAUT = 365
RECENT = timedelta(days=7)  # window of "last measurement received"
NODE_ID = r"^[a-z0-9][a-z0-9_-]{0,63}$"


# --- capteurs ------------------------------------------------------------------------


def calibration_due(type_: str, etalonnage: dict | None) -> date | None:
    """Date of the next calibration, None when the channel was never calibrated."""
    raw = (etalonnage or {}).get("date")
    if raw is None:
        return None
    try:
        last = date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None
    days = ETALONNAGE_JOURS.get(SensorType(type_), ETALONNAGE_DEFAUT)
    return last + timedelta(days=days)


class CapteurIn(BaseModel):
    materiel: str | None = Field(default=None, max_length=64)  # declared device (sht41-z1)
    noeud: str = Field(pattern=NODE_ID)
    zone: str = Field(pattern=ZONE_ID)
    type: SensorType
    emplacement: str | None = None  # soil probe of one emplacement
    modele: str | None = None
    cuve_id: str | None = None
    etalonnage: dict | None = None  # {date, methode, coefficients}
    plage_min: float | None = None
    plage_max: float | None = None
    emplacements_couverts: list[str] | None = None  # None: every emplacement of the zone


class CapteurPatch(BaseModel):
    materiel: str | None = Field(default=None, max_length=64)
    modele: str | None = None
    cuve_id: str | None = None
    etalonnage: dict | None = None
    plage_min: float | None = None
    plage_max: float | None = None
    emplacements_couverts: list[str] | None = None


def _links(s, cid: str, zone: str, couverts: list[str] | None) -> None:
    s.execute(delete(m.CapteurEmplacement).where(m.CapteurEmplacement.capteur_id == cid))
    if couverts is None:
        couverts = list(s.scalars(select(m.Emplacement.id).where(m.Emplacement.zone_id == zone)))
    for e in couverts:
        if get(s, m.Emplacement, e, "emplacement").zone_id != zone:
            raise HTTPException(422, f"{e} n'est pas dans la zone {zone}")
        s.add(m.CapteurEmplacement(capteur_id=cid, emplacement_id=e))
    s.flush()


def _capteur(c: m.Capteur, couverts: list[str], last: tuple | None, today: date) -> dict:
    due = calibration_due(c.type, c.etalonnage)
    return dict(
        row(c),
        emplacements_couverts=couverts,
        derniere_mesure=dict(ts=utc(last[0]), valeur=last[1]) if last else None,
        etalonnage_echeance=due,
        etalonnage_en_retard=due is not None and due < today,
    )


@router.get("/capteurs")
def list_capteurs(s: Db, now: Now, zone: str | None = None) -> list[dict]:
    q = select(m.Capteur).order_by(m.Capteur.zone, m.Capteur.id)
    if zone:
        q = q.where(m.Capteur.zone == zone)
    rows = list(s.scalars(q))
    links: dict[str, list[str]] = {}
    for cid, eid in s.execute(
        select(m.CapteurEmplacement.capteur_id, m.CapteurEmplacement.emplacement_id).order_by(
            m.CapteurEmplacement.emplacement_id
        )
    ):
        links.setdefault(cid, []).append(eid)
    latest = s.execute(
        select(m.Mesure.capteur_id, func.max(m.Mesure.ts))
        .where(m.Mesure.ts >= now - RECENT)
        .group_by(m.Mesure.capteur_id)
    ).all()
    last, ids = {}, {c.id for c in rows}
    for cid, ts in latest:
        if cid in ids:
            v = s.scalar(
                select(m.Mesure.valeur).where(m.Mesure.capteur_id == cid, m.Mesure.ts == ts)
            )
            last[cid] = (ts, v)
    today = now.date()
    return [_capteur(c, links.get(c.id, []), last.get(c.id), today) for c in rows]


@router.post("/capteurs", status_code=201)
def create_capteur(body: CapteurIn, s: Db, now: Now) -> dict:
    get(s, m.Zone, body.zone, "zone")
    if body.emplacement is not None:
        get(s, m.Emplacement, body.emplacement, "emplacement")
    cid = capteur_id(body.noeud, body.type.value, body.emplacement)
    absent(s, m.Capteur, cid, "capteur")
    c = m.Capteur(id=cid, **body.model_dump(mode="json", exclude={"emplacements_couverts"}))
    s.add(c)
    s.flush()
    couverts = [body.emplacement] if body.emplacement else body.emplacements_couverts
    _links(s, cid, body.zone, couverts)
    return _capteur(c, _covered(s, cid), None, now.date())


def _covered(s, cid: str) -> list[str]:
    return list(
        s.scalars(
            select(m.CapteurEmplacement.emplacement_id)
            .where(m.CapteurEmplacement.capteur_id == cid)
            .order_by(m.CapteurEmplacement.emplacement_id)
        )
    )


@router.patch("/capteurs/{cid}")
def update_capteur(cid: str, body: CapteurPatch, s: Db, now: Now) -> dict:
    c = get(s, m.Capteur, cid, "capteur")
    patch(c, body, skip=("emplacements_couverts",))
    if "emplacements_couverts" in body.model_fields_set and c.emplacement is None:
        _links(s, cid, c.zone, body.emplacements_couverts)
    s.flush()
    return _capteur(c, _covered(s, cid), None, now.date())


@router.delete("/capteurs/{cid}", status_code=204)
def delete_capteur(cid: str, s: Db) -> None:
    """The channel only: its measurements stay (the ingestion registers it again if the
    node keeps publishing)."""
    c = get(s, m.Capteur, cid, "capteur")
    s.execute(delete(m.CapteurEmplacement).where(m.CapteurEmplacement.capteur_id == cid))
    s.delete(c)


# --- actionneurs ---------------------------------------------------------------------


class ActionneurIn(BaseModel):
    id: str = Field(pattern=NODE_ID)
    zone_id: str = Field(pattern=ZONE_ID)
    type: Actuator
    noeud: str = Field(pattern=NODE_ID)
    commande: str = Field(default="on_off", pattern=r"^(on_off|pwm)$")
    puissance_w: float | None = Field(default=None, ge=0)
    debit_l_h: float | None = Field(default=None, ge=0)
    debit_ml_min: float | None = Field(default=None, ge=0)
    ppfd_max: float | None = Field(default=None, ge=0)
    duree_max_s: float | None = Field(default=None, gt=0)
    parametres: dict | None = None


class ActionneurPatch(BaseModel):
    noeud: str | None = Field(default=None, pattern=NODE_ID)
    commande: str | None = Field(default=None, pattern=r"^(on_off|pwm)$")
    puissance_w: float | None = Field(default=None, ge=0)
    debit_l_h: float | None = Field(default=None, ge=0)
    debit_ml_min: float | None = Field(default=None, ge=0)
    ppfd_max: float | None = Field(default=None, ge=0)
    duree_max_s: float | None = Field(default=None, gt=0)
    parametres: dict | None = None


def _state(s, zone: str, type_: str) -> dict | None:
    e = s.scalars(
        select(m.EtatActionneur)
        .where(m.EtatActionneur.zone == zone, m.EtatActionneur.actionneur == type_)
        .order_by(m.EtatActionneur.ts.desc())
        .limit(1)
    ).first()
    return dict(ts=utc(e.ts), action=e.action, valeur=e.valeur) if e else None


def actuator_row(s, a: m.Actionneur) -> dict:
    return dict(row(a), etat=_state(s, a.zone_id, a.type))


@router.get("/actionneurs")
def list_actionneurs(s: Db, zone: str | None = None) -> list[dict]:
    q = select(m.Actionneur).order_by(m.Actionneur.zone_id, m.Actionneur.id)
    if zone:
        q = q.where(m.Actionneur.zone_id == zone)
    return [actuator_row(s, a) for a in s.scalars(q)]


@router.post("/actionneurs", status_code=201)
def create_actionneur(body: ActionneurIn, s: Db) -> dict:
    get(s, m.Zone, body.zone_id, "zone")
    absent(s, m.Actionneur, body.id, "actionneur")
    same = s.scalars(
        select(m.Actionneur).where(
            m.Actionneur.zone_id == body.zone_id, m.Actionneur.type == body.type.value
        )
    ).first()
    if same is not None:
        raise HTTPException(
            409, f"la zone {body.zone_id} a déjà un actionneur {body.type} ({same.id})"
        )
    a = m.Actionneur(**body.model_dump(mode="json"))
    s.add(a)
    s.flush()
    return actuator_row(s, a)


@router.get("/actionneurs/{aid}")
def get_actionneur(aid: str, s: Db) -> dict:
    return actuator_row(s, get(s, m.Actionneur, aid, "actionneur"))


@router.patch("/actionneurs/{aid}")
def update_actionneur(aid: str, body: ActionneurPatch, s: Db) -> dict:
    a = get(s, m.Actionneur, aid, "actionneur")
    patch(a, body)
    s.flush()
    return actuator_row(s, a)


@router.delete("/actionneurs/{aid}", status_code=204)
def delete_actionneur(aid: str, s: Db) -> None:
    s.delete(get(s, m.Actionneur, aid, "actionneur"))


# --- caméras -------------------------------------------------------------------------


class CameraIn(BaseModel):
    id: str = Field(pattern=NODE_ID)
    zone_id: str = Field(pattern=ZONE_ID)


class CameraPatch(BaseModel):
    zone_id: str = Field(pattern=ZONE_ID)


class Region(BaseModel):
    emplacement_id: str
    # [x, y, w, h] normalised to [0, 1]; None: visible emplacement without a region
    bbox: tuple[float, float, float, float] | None = None


class Regions(BaseModel):
    regions: list[Region]


def _camera(s, c: m.Camera) -> dict:
    regions = s.scalars(
        select(m.CameraRegion)
        .where(m.CameraRegion.camera_id == c.id)
        .order_by(m.CameraRegion.emplacement_id)
    )
    return dict(
        row(c),
        regions=[dict(emplacement_id=r.emplacement_id, bbox=r.bbox) for r in regions],
        derniere_image=_last_image(s, c.id),
    )


def _last_image(s, camera: str) -> dict | None:
    v = s.scalars(
        select(m.VisionResultat)
        .where(m.VisionResultat.camera == camera)
        .order_by(m.VisionResultat.ts.desc())
        .limit(1)
    ).first()
    return dict(image_id=v.image_id, ts=utc(v.ts)) if v else None


@router.get("/cameras")
def list_cameras(s: Db, zone: str | None = None) -> list[dict]:
    q = select(m.Camera).order_by(m.Camera.id)
    if zone:
        q = q.where(m.Camera.zone_id == zone)
    return [_camera(s, c) for c in s.scalars(q)]


@router.post("/cameras", status_code=201)
def create_camera(body: CameraIn, s: Db) -> dict:
    get(s, m.Zone, body.zone_id, "zone")
    absent(s, m.Camera, body.id, "caméra")
    c = m.Camera(**body.model_dump())
    s.add(c)
    s.flush()
    return _camera(s, c)


@router.get("/cameras/{cam}")
def get_camera(cam: str, s: Db) -> dict:
    return _camera(s, get(s, m.Camera, cam, "caméra"))


@router.patch("/cameras/{cam}")
def update_camera(cam: str, body: CameraPatch, s: Db) -> dict:
    c = get(s, m.Camera, cam, "caméra")
    get(s, m.Zone, body.zone_id, "zone")
    if body.zone_id != c.zone_id:
        s.execute(delete(m.CameraRegion).where(m.CameraRegion.camera_id == cam))
    c.zone_id = body.zone_id
    s.flush()
    return _camera(s, c)


@router.delete("/cameras/{cam}", status_code=204)
def delete_camera(cam: str, s: Db) -> None:
    c = get(s, m.Camera, cam, "caméra")
    s.execute(delete(m.CameraRegion).where(m.CameraRegion.camera_id == cam))
    s.delete(c)


@router.put("/cameras/{cam}/regions")
def set_regions(cam: str, body: Regions, s: Db) -> dict:
    """Emplacements seen by the camera and their rectangle on the image (region editor)."""
    c = get(s, m.Camera, cam, "caméra")
    seen = set()
    for r in body.regions:
        e = get(s, m.Emplacement, r.emplacement_id, "emplacement")
        if e.zone_id != c.zone_id:
            raise HTTPException(422, f"{e.id} n'est pas dans la zone {c.zone_id} de {cam}")
        if e.id in seen:
            raise HTTPException(422, f"{e.id} en double")
        seen.add(e.id)
        if r.bbox is not None:
            x, y, w, h = r.bbox
            if min(x, y) < 0 or w <= 0 or h <= 0 or x + w > 1 + 1e-6 or y + h > 1 + 1e-6:
                raise HTTPException(422, f"région de {e.id} hors de l'image : {list(r.bbox)}")
    s.execute(delete(m.CameraRegion).where(m.CameraRegion.camera_id == cam))
    for r in body.regions:
        s.add(m.CameraRegion(camera_id=cam, emplacement_id=r.emplacement_id,
                             bbox=list(r.bbox) if r.bbox else None))  # fmt: skip
    s.flush()
    return _camera(s, c)


@router.get("/cameras/{cam}/derniere-image")
def last_image(cam: str, s: Db) -> dict:
    get(s, m.Camera, cam, "caméra")
    img = _last_image(s, cam)
    if img is None:
        raise HTTPException(404, f"aucune image reçue de {cam}")
    return img


# --- noeuds --------------------------------------------------------------------------


@router.get("/noeuds")
def list_noeuds(s: Db, now: Now) -> list[dict]:
    """Nodes known from their status (`serre/<noeud>/status`) or from the configuration."""
    status: dict[str, tuple[datetime, str]] = {}
    for n, ts in s.execute(
        select(m.NoeudStatus.noeud, func.max(m.NoeudStatus.ts)).group_by(m.NoeudStatus.noeud)
    ).all():
        st = s.scalar(select(m.NoeudStatus.status).where(m.NoeudStatus.noeud == n,
                                                         m.NoeudStatus.ts == ts))  # fmt: skip
        status[n] = (ts, st)
    last = dict(
        s.execute(
            select(m.Mesure.noeud, func.max(m.Mesure.ts))
            .where(m.Mesure.ts >= now - RECENT)
            .group_by(m.Mesure.noeud)
        ).all()
    )
    names = set(status) | set(s.scalars(select(m.Capteur.noeud).distinct()))
    names |= set(s.scalars(select(m.Actionneur.noeud).distinct()))
    zones: dict[str, set[str]] = {}
    for n, z in s.execute(select(m.Capteur.noeud, m.Capteur.zone).distinct()):
        zones.setdefault(n, set()).add(z)
    for n, z in s.execute(select(m.Actionneur.noeud, m.Actionneur.zone_id).distinct()):
        zones.setdefault(n, set()).add(z)
    return [
        dict(
            id=n,
            status=status[n][1] if n in status else None,
            status_ts=utc(status[n][0]) if n in status else None,
            derniere_mesure=utc(last[n]) if n in last else None,
            zones=sorted(zones.get(n, ())),
        )
        for n in sorted(names)
    ]
