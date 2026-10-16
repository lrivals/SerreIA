"""MQTT → database ingestion (docs/09 §7).

Subscribes to the `SUBSCRIPTIONS` of the contract, validates every message with
`common.mqtt.decode` and writes it to its table. Invalid payloads are logged and counted,
never raised: one broken node must not stop the ingestion. Rows are written in batches
(every `batch_size` rows or `flush_s` seconds, and on `flush()` / `close()`); duplicates
(QoS 1 redelivery, retained messages replayed at reconnection) are ignored.
"""

import logging
import threading
import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import Table, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from common.mqtt import SUBSCRIPTIONS, TopicKind, decode, parse_raison, parse_topic
from common.mqtt.schemas import (
    ActuatorState,
    Alert,
    CaptureRequest,
    Command,
    Decision,
    SensorReading,
    VisionResult,
)
from edge.controller.config import capteur_id, resolve_emplacement

from .. import traceability
from ..agent import consignes
from ..db import models as m
from ..db.session import insert, utc

log = logging.getLogger(__name__)

MAX_PENDING = 200_000  # rows kept while the database is unreachable


class Ingestor:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        batch_size: int = 500,
        flush_s: float = 1.0,
        clock: Callable[[], datetime] | None = None,
    ):
        self.sessions, self.batch_size, self.flush_s = sessions, batch_size, flush_s
        self.clock = clock or (lambda: datetime.now(UTC))  # reception time (status)
        self.lock = threading.RLock()
        self.rows: dict[Table, list[dict]] = defaultdict(list)
        self.decisions: dict[str, dict] = {}
        self.new_capteurs: dict[str, dict] = {}
        self.recus = self.rejets = self.ecrits = 0
        self._last_flush = time.monotonic()
        self.reload()

    def reload(self) -> None:
        """Re-read the configuration used to enrich the rows (after a seed / UI change)."""
        with self.sessions() as s:
            self.actuators = {(a.zone_id, a.type): a.id for a in s.scalars(select(m.Actionneur))}
            self.emplacements = set(s.scalars(select(m.Emplacement.id)))
            self.capteurs = set(s.scalars(select(m.Capteur.id)))
            self.regions: dict[str, list[tuple[str, list[float] | None]]] = defaultdict(list)
            for r in s.scalars(select(m.CameraRegion)):
                self.regions[r.camera_id].append((r.emplacement_id, r.bbox))

    def attach(self, bus) -> None:
        """`bus`: anything with `subscribe(pattern, handler)` (MqttPublisher, LoopbackBus…)."""
        for pattern in SUBSCRIPTIONS.values():
            bus.subscribe(pattern, self.on_message)

    # --- reception -------------------------------------------------------------------

    def on_message(self, topic: str, payload: bytes) -> None:
        try:
            parsed = parse_topic(topic)
            message = decode(topic, payload)
        except ValueError as e:  # pydantic's ValidationError is a ValueError
            with self.lock:
                self.rejets += 1
            log.warning("message rejeté sur %s : %s", topic, str(e).splitlines()[0])
            return
        with self.lock:
            self.recus += 1
            self._add(parsed.kind, parsed.scope, parsed.subject, message)
            if (
                self.pending >= self.batch_size
                or time.monotonic() - self._last_flush >= self.flush_s
            ):
                self._flush()

    def _add(self, kind: TopicKind, scope: str, subject: str | None, msg) -> None:
        match kind:
            case TopicKind.CAPTEUR:
                self._sensor(scope, subject, msg)
            case TopicKind.VISION:
                self._vision(scope, msg)
            case TopicKind.ALERTE:
                self._alert(scope, msg)
            case TopicKind.CMD:
                self._command(scope, subject, msg)
            case TopicKind.ETAT:
                self._state(scope, subject, msg)
            case TopicKind.STATUS:
                row = dict(ts=utc(self.clock()), noeud=scope, status=msg)
                self.rows[m.NoeudStatus.__table__].append(row)
            case TopicKind.DECISION:
                self._decision(msg)

    def _sensor(self, zone: str, sensor: str, r: SensorReading) -> None:
        cid = capteur_id(r.noeud, sensor, r.emplacement)
        if cid not in self.capteurs and cid not in self.new_capteurs:
            self.new_capteurs[cid] = dict(
                id=cid, noeud=r.noeud, zone=zone, type=sensor, emplacement=r.emplacement
            )
        self.rows[m.Mesure.__table__].append(
            dict(
                ts=utc(r.ts),
                capteur_id=cid,
                zone=zone,
                type=sensor,
                noeud=r.noeud,
                emplacement=r.emplacement,
                valeur=r.valeur,
                unite=r.unite,
                qualite=r.qualite,
            )
        )

    def _vision(self, zone: str, v: VisionResult) -> None:
        regions = self.regions.get(v.camera, [])
        for i, d in enumerate(v.detections):
            self.rows[m.VisionResultat.__table__].append(
                dict(
                    ts=utc(v.ts),
                    image_id=v.image_id,
                    idx=i,
                    zone=zone,
                    camera=v.camera,
                    emplacement_id=resolve_emplacement(d.bbox, regions),
                    modele=v.modele,
                    espece=d.espece,
                    espece_conf=d.espece_conf,
                    sante=d.sante,
                    sante_conf=d.sante_conf,
                    classe=d.classe,
                    classe_conf=d.classe_conf,
                    bbox=list(d.bbox) if d.bbox is not None else None,
                    score_anomalie=v.score_anomalie,
                    surface_verte_px=v.surface_verte_px,
                )
            )

    def _alert(self, zone: str, a: Alert) -> None:
        self.rows[m.Alerte.__table__].append(
            dict(
                ts=utc(a.ts),
                id=uuid.uuid4().hex,
                zone=zone,
                niveau=a.niveau,
                message=a.message,
                source=a.source,
                acquittee=False,
            )
        )

    def _command(self, zone: str, subject: str, c: Command | CaptureRequest) -> None:
        if isinstance(c, CaptureRequest):
            row = dict(action="capture", valeur=None, duree_s=None, raison=None, camera=c.camera)
        else:
            row = dict(
                action=c.action, valeur=c.valeur, duree_s=c.duree_s, raison=c.raison, camera=None
            )
        row.update(
            ts=utc(c.ts),
            zone=zone,
            actionneur=subject,
            source=c.source,
            decision_id=parse_raison(row["raison"])[0],
        )
        self.rows[m.Commande.__table__].append(row)

    def _state(self, zone: str, actuator: str, s: ActuatorState) -> None:
        self.rows[m.EtatActionneur.__table__].append(
            dict(
                ts=utc(s.ts),
                zone=zone,
                actionneur=actuator,
                actionneur_id=self.actuators.get((zone, actuator)),
                action=s.action,
                valeur=s.valeur,
            )
        )

    def _decision(self, d: Decision) -> None:
        self.decisions[d.id] = traceability.stored_row(d)  # the last status received wins

    # --- writing ---------------------------------------------------------------------

    @property
    def pending(self) -> int:
        return sum(map(len, self.rows.values())) + len(self.decisions) + len(self.new_capteurs)

    def flush(self) -> None:
        with self.lock:
            self._flush()

    def _flush(self) -> None:
        self._last_flush = time.monotonic()
        if not self.pending:
            return
        try:
            with self.sessions.begin() as s:
                self._write(s)
        except SQLAlchemyError:
            log.exception("écriture en base impossible, %d lignes en attente", self.pending)
            if self.pending > MAX_PENDING:
                log.error("tampon plein : %d lignes abandonnées", self.pending)
                self._clear()
            return
        self.ecrits += self.pending
        self.capteurs |= set(self.new_capteurs)
        self._clear()

    def _write(self, s: Session) -> None:
        if self.new_capteurs:
            caps = list(self.new_capteurs.values())
            s.execute(insert(s, m.Capteur.__table__).on_conflict_do_nothing(), caps)
            links = [
                dict(capteur_id=c["id"], emplacement_id=c["emplacement"])
                for c in caps
                if c["emplacement"] in self.emplacements
            ]
            if links:
                table = m.CapteurEmplacement.__table__
                s.execute(insert(s, table).on_conflict_do_nothing(), links)
        for table, rows in self.rows.items():
            if rows:
                s.execute(insert(s, table).on_conflict_do_nothing(), rows)
        if self.decisions:
            stmt = insert(s, m.Decision.__table__)
            cols = [c for c in next(iter(self.decisions.values())) if c != "id"]
            stmt = stmt.on_conflict_do_update(
                index_elements=["id"], set_={c: stmt.excluded[c] for c in cols}
            )
            s.execute(stmt, list(self.decisions.values()))
        # Actions of the decisions (docs/10 §3), then their confirmation by etat/.
        traced = set(self.decisions)
        commands = self.rows.get(m.Commande.__table__, ())
        traced |= {r["decision_id"] for r in commands if r["decision_id"]}
        if traced:
            traceability.sync_actions(s, traced)
        traceability.reconcile(s, self.clock())
        consignes.restore_expired(s, self.clock())  # temporary setpoints of the agent

    def _clear(self) -> None:
        self.rows.clear()
        self.decisions.clear()
        self.new_capteurs.clear()

    def close(self) -> None:
        self.flush()
