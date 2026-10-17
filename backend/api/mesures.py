"""Measurements, vision and images (docs/12 §2.3, §3): time series of a zone, dashboard
of a zone (current values against the setpoints of the stage), classifications, JPEG of
the captures (received from the camera_service uploader, `edge/archive.py`)."""

import base64
import binascii
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy import select

from common.mqtt import SensorType, VisionResult
from edge.controller.config import HYDRO
from edge.controller.recipes import PlantStage, Recipe, Setpoints, zone_setpoints

from ..agent.tools import AGREGATS, _resample
from ..db import models as m
from ..db.session import utc
from ..traceability import decision_summary
from .crud import get
from .deps import Db, Now
from .equipements import actuator_row
from .serres import _vision

router = APIRouter(tags=["mesures"])

MAX_POINTS = 2000
IMAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MAX_JPEG = 15 * 1024 * 1024
TILE_SPARK = timedelta(minutes=30)  # step of the 24 h mini-curves of the dashboard
MARGIN = 0.10  # outside the range by less than 10 % of its width: "attention"


# --- mesures -------------------------------------------------------------------------


def series(
    s,
    zone: str,
    types: list[str],
    debut: datetime,
    fin: datetime,
    step: timedelta | None,
    max_points: int,
    emplacement: str | None = None,
) -> list[dict]:
    """One series per (type, emplacement): soil probes give one curve per emplacement."""
    q = select(m.Mesure.ts, m.Mesure.type, m.Mesure.emplacement, m.Mesure.valeur,
               m.Mesure.unite).where(
        m.Mesure.zone == zone, m.Mesure.type.in_(types), m.Mesure.qualite != "erreur",
        m.Mesure.ts >= debut, m.Mesure.ts < fin,
    )  # fmt: skip
    if emplacement:
        q = q.where(m.Mesure.emplacement == emplacement)
    groups: dict[tuple[str, str | None], list] = defaultdict(list)
    units = {}
    for ts, typ, emp, v, unite in s.execute(q.order_by(m.Mesure.ts)):
        groups[(typ, emp)].append((utc(ts), v))
        units[typ] = unite
    out = []
    for (typ, emp), pts in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
        values = [v for _, v in pts]
        out.append(
            dict(
                type=typ,
                emplacement=emp,
                unite=units[typ],
                n_mesures=len(pts),
                min=min(values),
                max=max(values),
                moyenne=round(sum(values) / len(values), 3),
                points=[[t, round(v, 3)] for t, v in _resample(pts, debut, fin, step, max_points)],
            )
        )
    return out


@router.get("/mesures")
def mesures(
    s: Db,
    now: Now,
    zone: str,
    type: Annotated[list[SensorType] | None, Query()] = None,
    emplacement: str | None = None,
    debut: datetime | None = None,
    fin: datetime | None = None,
    agregat: Literal["brut", "moy_15min", "moy_1h"] = "moy_15min",
    max_points: Annotated[int, Query(ge=10, le=MAX_POINTS)] = 500,
) -> dict:
    """Series of a zone over [debut, fin) (default: the last 24 h), averaged per `agregat`
    and widened so that each series keeps at most `max_points` points."""
    get(s, m.Zone, zone, "zone")
    fin = utc(fin) if fin else now
    debut = utc(debut) if debut else fin - timedelta(hours=24)
    types = [t.value for t in type] if type else [t.value for t in SensorType]
    return dict(
        zone=zone,
        debut=debut,
        fin=fin,
        agregat=agregat,
        series=series(s, zone, types, debut, fin, AGREGATS[agregat], max_points, emplacement),
    )


# --- tableau de bord -----------------------------------------------------------------


def zone_setpoints_db(s, zid: str) -> Setpoints | None:
    """Setpoints of a zone from the database (the controller computes the same from the
    published serre.yaml): intersection of the recipes of its current plants."""
    rows = s.execute(
        select(m.Plante)
        .join(m.Affectation, m.Affectation.plante_id == m.Plante.id)
        .join(m.Emplacement, m.Emplacement.id == m.Affectation.emplacement_id)
        .where(m.Affectation.fin.is_(None), m.Emplacement.zone_id == zid)
    ).scalars()
    plants = [PlantStage(p.recette_id, p.stade, p.prioritaire) for p in rows if p.recette_id]
    recipes = {}
    for r in s.scalars(select(m.Recette).where(m.Recette.id.in_({p.recette for p in plants}))):
        recipes[r.id] = Recipe.model_validate({"espece": r.espece, "stades": r.stades})
    plants = [p for p in plants if p.recette in recipes and p.stade in recipes[p.recette].stades]
    hydro = any(
        mode in HYDRO
        for mode in s.scalars(
            select(m.Emplacement.mode_culture).where(m.Emplacement.zone_id == zid)
        )
    )
    return zone_setpoints(plants, recipes, hydro)


def is_day(z: m.Zone, sp: Setpoints | None, now: datetime, fuseau: str) -> bool:
    """Inside the photoperiod [jour_debut, jour_debut + photoperiode_h) (local time)."""
    if sp is None:
        return True
    local = now.astimezone(ZoneInfo(fuseau))
    h, mn = (int(x) for x in z.jour_debut.split(":"))
    start = local.replace(hour=h, minute=mn, second=0, microsecond=0)
    if start > local:
        start -= timedelta(days=1)
    return local < start + timedelta(hours=sp.photoperiode_h)


def target(sp: Setpoints | None, typ: str, jour: bool) -> tuple[float, float] | None:
    if sp is None:
        return None
    if typ == SensorType.TEMPERATURE:
        return tuple(sp.temperature(jour))
    if typ == SensorType.CO2:
        return (0.0, sp.co2_max) if sp.co2_max else None
    if typ in (SensorType.HUMIDITE, SensorType.PH, SensorType.EC, SensorType.HUMIDITE_SOL):
        r = getattr(sp, typ)
        return tuple(r) if r is not None else None
    return None


def tile_status(valeur: float, plage: tuple[float, float] | None) -> str:
    """ok | attention | alerte | inconnu (no setpoint)."""
    if plage is None:
        return "inconnu"
    lo, hi = plage
    if lo <= valeur <= hi:
        return "ok"
    gap = lo - valeur if valeur < lo else valeur - hi
    return "attention" if gap <= MARGIN * max(hi - lo, 1e-9) else "alerte"


@router.get("/zones/{zid}/tableau")
def dashboard(zid: str, s: Db, now: Now) -> dict:
    """Dashboard of a zone (docs/12 §2.3): current values against the setpoint range,
    24 h mini-curves, actuator states, last image with its classifications, active
    alerts and proposals waiting for a validation."""
    z = get(s, m.Zone, zid, "zone")
    serre = s.get(m.Serre, z.serre_id)
    sp = zone_setpoints_db(s, zid)
    jour = is_day(z, sp, now, serre.fuseau if serre else "Europe/Paris")
    debut = now - timedelta(hours=24)
    curves = series(s, zid, [t.value for t in SensorType], debut, now, TILE_SPARK, 48)
    tiles = []
    for c in curves:
        q = select(m.Mesure).where(
            m.Mesure.zone == zid, m.Mesure.type == c["type"], m.Mesure.ts >= debut,
            m.Mesure.qualite != "erreur",
        )  # fmt: skip
        q = (
            q.where(m.Mesure.emplacement == c["emplacement"])
            if c["emplacement"]
            else q.where(m.Mesure.emplacement.is_(None))
        )
        last = s.scalars(q.order_by(m.Mesure.ts.desc()).limit(1)).first()
        if last is None:
            continue
        plage = target(sp, c["type"], jour)
        tiles.append(
            dict(
                type=c["type"],
                emplacement=c["emplacement"],
                valeur=last.valeur,
                unite=last.unite,
                qualite=last.qualite,
                ts=utc(last.ts),
                plage=plage,
                statut=tile_status(last.valeur, plage),
                points=c["points"],
            )
        )
    image = s.scalars(
        select(m.VisionResultat)
        .where(m.VisionResultat.zone == zid)
        .order_by(m.VisionResultat.ts.desc())
        .limit(1)
    ).first()
    detections = []
    if image is not None:
        detections = [
            dict(_vision(v), emplacement=v.emplacement_id)
            for v in s.scalars(
                select(m.VisionResultat)
                .where(m.VisionResultat.image_id == image.image_id)
                .order_by(m.VisionResultat.idx)
            )
        ]
    alerts = s.scalars(
        select(m.Alerte)
        .where(m.Alerte.zone == zid, m.Alerte.acquittee.is_(False))
        .order_by(m.Alerte.ts.desc())
        .limit(20)
    )
    proposals = s.scalars(
        select(m.Decision)
        .where(m.Decision.zone == zid, m.Decision.statut == "proposee")
        .order_by(m.Decision.ts.desc())
    )
    return dict(
        zone=dict(id=z.id, nom=z.nom),
        jour=jour,
        consignes=sp.as_evidence() if sp else None,
        mesures=tiles,
        actionneurs=[
            actuator_row(s, a)
            for a in s.scalars(
                select(m.Actionneur).where(m.Actionneur.zone_id == zid).order_by(m.Actionneur.id)
            )
        ],
        image=dict(
            image_id=image.image_id, ts=utc(image.ts), camera=image.camera, detections=detections
        )
        if image
        else None,  # fmt: skip
        alertes=[
            dict(id=a.id, ts=utc(a.ts), niveau=a.niveau, message=a.message, source=a.source)
            for a in alerts
        ],  # fmt: skip
        propositions=[
            decision_summary(d) for d in proposals if d.expire is None or utc(d.expire) > now
        ],
    )


# --- vision et images ----------------------------------------------------------------


@router.get("/vision")
def vision(
    s: Db,
    now: Now,
    emplacement: str | None = None,
    zone: str | None = None,
    debut: datetime | None = None,
    fin: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[dict]:
    fin = utc(fin) if fin else now
    debut = utc(debut) if debut else fin - timedelta(hours=72)
    q = select(m.VisionResultat).where(m.VisionResultat.ts >= debut, m.VisionResultat.ts < fin)
    if emplacement:
        q = q.where(m.VisionResultat.emplacement_id == emplacement)
    if zone:
        q = q.where(m.VisionResultat.zone == zone)
    rows = s.scalars(q.order_by(m.VisionResultat.ts.desc(), m.VisionResultat.idx).limit(limit))
    return [
        dict(_vision(v), zone=v.zone, emplacement=v.emplacement_id, modele=v.modele,
             score_anomalie=v.score_anomalie)
        for v in rows
    ]  # fmt: skip


def _images(request: Request) -> Path:
    return Path(request.app.state.settings.images)


def find_image(root: Path, image_id: str, suffix: str = ".jpg") -> Path | None:
    if not IMAGE_ID.fullmatch(image_id):
        raise HTTPException(422, f"identifiant d'image invalide {image_id!r}")
    name = f"{image_id}{suffix}"
    direct = root / name
    if direct.is_file():
        return direct
    return next(iter(sorted(root.glob(f"*/{name}"), reverse=True)), None) if root.is_dir() else None


@router.get("/images/{image_id}", response_class=FileResponse)
def image(image_id: str, request: Request, gradcam: bool = False) -> FileResponse:
    """The JPEG of a capture; `gradcam=1`: its Grad-CAM map (`<id>.gradcam.jpg`) when the
    camera_service or an offline replay produced one."""
    path = find_image(_images(request), image_id, ".gradcam.jpg" if gradcam else ".jpg")
    if path is None:
        what = "carte Grad-CAM" if gradcam else "image"
        raise HTTPException(404, f"{what} indisponible pour {image_id}")
    return FileResponse(path, media_type="image/jpeg")


class Upload(BaseModel):
    """Record sent by `edge.archive.Uploader` (`http_send`)."""

    resultat: dict
    extras: dict = {}
    jpeg_b64: str | None = None


@router.post("/images", status_code=201)
def upload(body: Upload, request: Request) -> dict:
    """Archive of the captures on the server (the results themselves come by MQTT)."""
    try:
        result = VisionResult.model_validate(body.resultat)
    except ValidationError as e:
        raise HTTPException(422, f"résultat de vision invalide : {e}") from e
    if not IMAGE_ID.fullmatch(result.image_id):
        raise HTTPException(422, f"identifiant d'image invalide {result.image_id!r}")
    day = _images(request) / f"{result.ts:%Y-%m-%d}"
    day.mkdir(parents=True, exist_ok=True)
    if body.jpeg_b64 is not None:
        try:
            jpeg = base64.b64decode(body.jpeg_b64, validate=True)
        except binascii.Error as e:
            raise HTTPException(422, "jpeg_b64 invalide") from e
        if len(jpeg) > MAX_JPEG or not jpeg.startswith(b"\xff\xd8"):
            raise HTTPException(422, "JPEG invalide ou trop gros")
        (day / f"{result.image_id}.jpg").write_bytes(jpeg)
    record = {"resultat": body.resultat, "extras": body.extras}
    (day / f"{result.image_id}.json").write_text(json.dumps(record, ensure_ascii=False))
    return dict(image_id=result.image_id, jpeg=body.jpeg_b64 is not None)
