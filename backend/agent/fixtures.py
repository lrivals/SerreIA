"""Reference history of the agent (docs/16 §4, "mildiou et agent"), written straight in the
database: the base of the tests and of `backend.agent.eval`. `history_from_scenario` finds
the same identifiers in the history simulated by `sim --scenario mildiou --figer`.

Three days in z1 up to `NOW` (13 October 2026, 15:00 local):
- humid nights (HR 92 % from 20:00 to 08:00, about 17.8 °C), drier days;
- night 2: three `VisionResult` `tomate/maladie/mildiou` on z1-A1 (cam-z1-a, 0.62 → 0.74 →
  0.81, one per hour up to 02:00), then decision `maladie.mildiou.ventilation` at 02:30
  with its vision and sensor evidence, its command (ventilo on 900 s) and the states, and
  the proposal `maladie.mildiou.isolement`, expired;
- one watering per day (sol.arrosage, 45 s, 1.5 L), day 3 dark (low lux);
- the daily consumption computed (`backend.consumption.compute_day`).
"""

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, sessionmaker

from common.mqtt import Decision, Ordre, command_raison

from ..consumption import compute_day, summary
from ..db import models as m
from ..db.seed import seed
from ..db.session import init_db, make_engine, make_sessions
from ..traceability import reconcile, stored_row, sync_actions

TZ = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 10, 13, 15, 0, tzinfo=TZ).astimezone(UTC)
START = NOW - timedelta(days=3)
STEP = timedelta(minutes=10)
MILDIOU_ID = "dec-20261012-0030-z1-007"
ISOLEMENT_ID = "dec-20261012-0030-z1-008"
IMAGES = ["z1-a-20261011T220000", "z1-a-20261011T230000", "z1-a-20261012T000000"]
CONFS = [0.62, 0.74, 0.81]


@dataclass(frozen=True)
class History:
    now: datetime
    mildiou: str
    isolement: str
    images: list[str]
    arrosages: list[str]
    humectation: str = "11"  # hours of HR > 90 % cited by the mildew decision
    litres: str = "4,5"  # water of the week (get_consommation)


def _local_hour(ts: datetime) -> float:
    lt = ts.astimezone(TZ)
    return lt.hour + lt.minute / 60


def _night(ts: datetime) -> bool:
    h = _local_hour(ts)
    return h >= 20 or h < 8


def _mesure(ts, type_, valeur, unite, noeud="esp32-01", zone="z1", emplacement=None) -> m.Mesure:
    suffix = f"-{emplacement}" if emplacement else ""
    return m.Mesure(ts=ts, capteur_id=f"{noeud}-{type_}{suffix}", zone=zone, type=type_,
                    noeud=noeud, emplacement=emplacement, valeur=valeur, unite=unite,
                    qualite="ok")  # fmt: skip


def _measures(s: Session) -> None:
    ts = START
    while ts < NOW:
        night = _night(ts)
        h = _local_hour(ts)
        dark_day = ts.astimezone(TZ).date() == NOW.astimezone(TZ).date()
        lux = 0.0
        if 7 <= h <= 19:
            lux = 30000 * math.sin(math.pi * (h - 7) / 12) * (0.25 if dark_day else 1.0)
        s.add_all([
            _mesure(ts, "temperature", 17.8 if night else 22.0, "°C"),
            _mesure(ts, "humidite", 92.0 if night else 70.0, "%"),
            _mesure(ts, "lux", round(lux, 1), "lx"),
            _mesure(ts, "humidite_sol", 55.0, "%", noeud="esp32-02", emplacement="z1-A1"),
            _mesure(ts, "niveau_cuve", 60.0, "%", noeud="esp32-03", zone="z2"),
        ])  # fmt: skip
        ts += STEP


def _vision(s: Session) -> None:
    first = datetime(2026, 10, 12, 0, 0, tzinfo=TZ).astimezone(UTC)
    for i, (image, conf) in enumerate(zip(IMAGES, CONFS, strict=True)):
        ts = first + timedelta(hours=i)
        s.add(
            m.VisionResultat(ts=ts, image_id=image, idx=0, zone="z1", camera="cam-z1-a",
                             emplacement_id="z1-A1", modele="clf-effnet-b0-v3", espece="tomate",
                             espece_conf=0.97, sante="anormal", sante_conf=0.9,
                             classe="tomate/maladie/mildiou", classe_conf=conf,
                             bbox=[0.0, 0.0, 0.5, 1.0], score_anomalie=0.4,
                             surface_verte_px=118000 - 1500 * i)
        )  # fmt: skip
        s.add(
            m.VisionResultat(ts=ts, image_id=image, idx=1, zone="z1", camera="cam-z1-a",
                             emplacement_id="z1-A2", modele="clf-effnet-b0-v3", espece="basilic",
                             espece_conf=0.95, sante="sain", sante_conf=0.93,
                             classe="basilic/sain", classe_conf=0.93,
                             bbox=[0.5, 0.0, 0.5, 1.0], score_anomalie=0.1,
                             surface_verte_px=42000)
        )  # fmt: skip


def _decision(s: Session, d: Decision) -> None:
    s.merge(m.Decision(**stored_row(d)))
    s.flush()


def _command(s, ts, actuator, action, duree_s, decision_id, texte, valeur=None) -> None:
    s.add(
        m.Commande(ts=ts, zone="z1", actionneur=actuator, action=action, valeur=valeur,
                   duree_s=duree_s, source="controller",
                   raison=command_raison(decision_id, texte), decision_id=decision_id)
    )  # fmt: skip
    s.add(
        m.EtatActionneur(
            ts=ts + timedelta(seconds=1),
            zone="z1",
            actionneur=actuator,
            actionneur_id=f"{actuator}-z1",
            action=action,
            valeur=valeur,
        )
    )
    if duree_s:
        s.add(m.EtatActionneur(ts=ts + timedelta(seconds=duree_s + 1), zone="z1",
                               actionneur=actuator, actionneur_id=f"{actuator}-z1",
                               action="off"))  # fmt: skip


def _mildew(s: Session) -> None:
    ts = datetime(2026, 10, 12, 2, 30, tzinfo=TZ).astimezone(UTC)
    vision = dict(camera="cam-z1-a", image_id=IMAGES[-1], modele="clf-effnet-b0-v3",
                  classe="tomate/maladie/mildiou", classe_conf=CONFS[-1], sante="anormal",
                  sante_conf=0.9, espece="tomate", espece_conf=0.97, emplacement="z1-A1",
                  confirmations=3)  # fmt: skip
    capteurs = [
        dict(topic="serre/z1/capteur/humidite", agregat="duree_au_dessus", valeur=11.0,
             unite="h", seuil=90.0),
        dict(topic="serre/z1/capteur/temperature", agregat="moyenne_12h", valeur=17.8,
             unite="°C"),
    ]  # fmt: skip
    why = (
        "tomate/maladie/mildiou confirmé sur z1-A1 (3 captures, conf 0,81) et HR > 90 % "
        "depuis 11 h à 17,8 °C"
    )
    _decision(s, Decision(
        id=MILDIOU_ID, ts=ts, zone="z1", emplacements=["z1-A1"], niveau=1, origine="controller",
        regle={"id": "maladie.mildiou.ventilation", "version": 1}, type="exceptionnelle",
        config_version=1, preuves=dict(vision=[vision], capteurs=capteurs),
        explication=f"{why} → ventilation 15 min, alerte",
        actions=["cmd:ventilo on 900 s", "alerte"], statut="executee",
    ))  # fmt: skip
    _command(s, ts + timedelta(seconds=1), "ventilo", "on", 900.0, MILDIOU_ID, "mildiou")
    s.add(
        m.Alerte(
            ts=ts,
            id="al-z1-mildiou",
            zone="z1",
            niveau="warning",
            message="z1 : mildiou probable sur z1-A1",
            source="controller",
        )
    )
    _decision(s, Decision(
        id=ISOLEMENT_ID, ts=ts, zone="z1", emplacements=["z1-A1"], niveau=1,
        origine="controller", regle={"id": "maladie.mildiou.isolement", "version": 1},
        type="exceptionnelle", config_version=1, preuves=dict(vision=[vision]),
        explication=f"{why} → isoler la plante", actions=["proposee:plante z1-A1 isolee"],
        ordres=[Ordre(cible="plante:z1-A1", action="isolee")], statut="proposee",
        expire=ts + timedelta(hours=2),
    ))  # fmt: skip


def _waterings(s: Session) -> list[str]:
    ids = []
    for day in (10, 11, 12):
        ts = datetime(2026, 10, day, 7, 0, tzinfo=TZ).astimezone(UTC)
        did = f"dec-202610{day}-0500-z1-001"
        _decision(s, Decision(
            id=did, ts=ts, zone="z1", emplacements=["z1-A1"], niveau=1, origine="controller",
            regle={"id": "sol.arrosage", "version": 1}, type="routine", config_version=1,
            preuves=dict(capteurs=[dict(topic="serre/z1/capteur/humidite_sol", valeur=39.0,
                                        unite="%", seuil=40.0, emplacement="z1-A1")]),
            explication="humidité du sol z1-A1 39 % < 40 % → arrosage 45 s",
            actions=["cmd:pompe_nutri on 45 s"], statut="executee",
        ))  # fmt: skip
        _command(s, ts + timedelta(seconds=1), "pompe_nutri", "on", 45.0, did, "arrosage")
        ids.append(did)
    return ids


def build_history(sessions: sessionmaker[Session], now: datetime = NOW) -> History:
    """Seed the database with serre.yaml (plants assigned before `START`) and write the
    history; returns the ids the reference questions refer to."""
    from edge.controller.config import load_greenhouse

    with sessions.begin() as s:
        seed(s, load_greenhouse(), START - timedelta(days=1))
    with sessions.begin() as s:
        _measures(s)
        _vision(s)
        _mildew(s)
        arrosages = _waterings(s)
        s.flush()
        sync_actions(s, [MILDIOU_ID, ISOLEMENT_ID, *arrosages])
        reconcile(s, now)
        first = START.astimezone(TZ).date()
        for i in range((now.astimezone(TZ).date() - first).days + 1):
            compute_day(s, first + timedelta(days=i), now)
    return History(now, MILDIOU_ID, ISOLEMENT_ID, list(IMAGES), arrosages)


def history_from_scenario(sessions: sessionmaker[Session], now: datetime) -> History:
    """The identifiers of the reference questions in a simulated history (scenario 2 of
    docs/16, `python -m sim --scenario mildiou --figer`): the first mildew decision with
    vision evidence, the first isolation proposal, the confirming images, the waterings."""
    from sqlalchemy import select

    with sessions() as s:
        decisions = list(s.scalars(select(m.Decision).order_by(m.Decision.ts)))
        mildiou = next(
            d for d in decisions
            if d.regle_id == "maladie.mildiou.ventilation" and (d.preuves or {}).get("vision")
        )  # fmt: skip
        isolement = next(
            (d.id for d in decisions if d.regle_id == "maladie.mildiou.isolement"), mildiou.id
        )
        images = sorted({v["image_id"] for v in mildiou.preuves["vision"]})
        if len(images) < 2:  # the evidence keeps the latest capture: its confirmations too
            rows = s.scalars(
                select(m.VisionResultat.image_id)
                .where(m.VisionResultat.emplacement_id.in_(mildiou.emplacements or ["z1-A1"]),
                       m.VisionResultat.classe.like("%/mildiou"), m.VisionResultat.ts <= mildiou.ts)
                .order_by(m.VisionResultat.ts)
            )  # fmt: skip
            images = list(dict.fromkeys(rows))[-3:]
        arrosages = [d.id for d in decisions if d.regle_id == "sol.arrosage"]
        wet = next(c["valeur"] for c in mildiou.preuves.get("capteurs", [])
                   if c.get("agregat") == "duree_au_dessus")  # fmt: skip
        litres = summary(s, "semaine", None, None, now)["totaux"]["litres"]  # as get_consommation
    fr = lambda x: f"{x:.1f}".rstrip("0").rstrip(".").replace(".", ",")  # noqa: E731
    return History(now, mildiou.id, isolement, images, arrosages, fr(wet), fr(litres))


def history_db(url: str = "sqlite://"):
    """A new database holding the reference history: (sessions, History)."""
    engine = make_engine(url)
    init_db(engine)
    sessions = make_sessions(engine)
    return sessions, build_history(sessions)
