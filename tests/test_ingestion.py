"""MQTT → database ingestion (docs/09 §7): one row per message, enrichment, robustness."""

from datetime import timedelta

from sqlalchemy import func, select

from backend.db import models as m
from backend.ingestion.mqtt_ingest import Ingestor, capteur_id, resolve_emplacement
from common.mqtt import (
    ActuatorState,
    Alert,
    CaptureRequest,
    Command,
    Decision,
    Detection,
    PreuveCapteur,
    Preuves,
    RegleRef,
    SensorReading,
    VisionResult,
    alert_topic,
    capture_topic,
    cmd_topic,
    command_raison,
    decision_topic,
    encode,
    sensor_topic,
    state_topic,
    status_topic,
    vision_topic,
)

from .backend_utils import T0, seeded_db


def ingestor(**kw):
    _, sessions = seeded_db()
    return Ingestor(sessions, clock=lambda: T0, **kw), sessions


def send(ing, topic, message):
    ing.on_message(topic, encode(message))


def rows(sessions, model):
    with sessions() as s:
        return s.scalars(select(model)).all()


def decision(statut="creee"):
    return Decision(
        ts=T0,
        id="dec-20260715-1000-z1-001",
        zone="z1",
        niveau=1,
        origine="controller",
        regle=RegleRef(id="climat.temperature.ventilation", version=1),
        type="routine",
        config_version=1,
        preuves=Preuves(
            capteurs=[PreuveCapteur(topic="serre/z1/capteur/temperature", valeur=28.0, unite="°C")]
        ),
        explication="T° 28 °C > 27 °C → ventilation",
        actions=["cmd:ventilo on 900 s"],
        statut=statut,
    )


def test_every_topic_kind_is_written():
    ing, sessions = ingestor()
    r = SensorReading(ts=T0, noeud="esp32-01", valeur=23.4, unite="°C", qualite="ok")
    send(ing, sensor_topic("z1", "temperature"), r)
    det = Detection(
        bbox=None,
        espece="tomate",
        espece_conf=0.97,
        sante="sain",
        sante_conf=0.9,
        classe="tomate/sain",
        classe_conf=0.9,
    )
    v = VisionResult(
        ts=T0,
        camera="cam-z1-a",
        image_id="z1-a-1",
        modele="clf",
        detections=[det, det.model_copy(update={"bbox": (0.1, 0.1, 0.2, 0.2)})],
        score_anomalie=0.1,
        surface_verte_px=1000,
    )
    send(ing, vision_topic("z1", "cam-z1-a"), v)
    send(ing, alert_topic("z1"), Alert(ts=T0, niveau="warning", message="HR", source="ctl"))
    c = Command(
        ts=T0,
        action="on",
        duree_s=900,
        source="controller",
        raison=command_raison("dec-20260715-1000-z1-001", "T° haute"),
    )
    send(ing, cmd_topic("z1", "ventilo"), c)
    send(ing, capture_topic("z1"), CaptureRequest(ts=T0, source="dashboard", camera="cam-z1-a"))
    send(ing, state_topic("z1", "ventilo"), ActuatorState(ts=T0, action="pwm", valeur=60))
    send(ing, status_topic("esp32-01"), "offline")
    send(ing, decision_topic("z1"), decision())
    ing.close()

    assert ing.recus == 8 and ing.rejets == 0
    (mesure,) = rows(sessions, m.Mesure)
    assert (mesure.capteur_id, mesure.zone, mesure.type, mesure.valeur) == (
        "esp32-01-temperature",
        "z1",
        "temperature",
        23.4,
    )
    assert [d.idx for d in rows(sessions, m.VisionResultat)] == [0, 1]
    assert rows(sessions, m.Alerte)[0].niveau == "warning"
    cmds = {c.actionneur: c for c in rows(sessions, m.Commande)}
    assert cmds["ventilo"].decision_id == "dec-20260715-1000-z1-001"
    assert cmds["capture"].action == "capture" and cmds["capture"].camera == "cam-z1-a"
    (etat,) = rows(sessions, m.EtatActionneur)
    assert (etat.actionneur_id, etat.action, etat.valeur) == ("ventilo-z1", "pwm", 60)
    (status,) = rows(sessions, m.NoeudStatus)
    assert (status.noeud, status.status) == ("esp32-01", "offline")
    (dec,) = rows(sessions, m.Decision)
    assert dec.regle_id == "climat.temperature.ventilation" and dec.niveau == "1"
    assert dec.preuves["capteurs"][0]["valeur"] == 28.0


def test_sensors_are_registered_and_linked_to_their_emplacement():
    ing, sessions = ingestor()
    declared = len(rows(sessions, m.Capteur))
    for t in range(3):
        for noeud in ("esp32-06", "esp32-02"):  # undeclared probe, declared one
            r = SensorReading(
                ts=T0 + timedelta(minutes=t),
                noeud=noeud,
                valeur=40.0,
                unite="%",
                qualite="ok",
                emplacement="z1-A1",
            )
            send(ing, sensor_topic("z1", "humidite_sol"), r)
    ing.close()
    cid = capteur_id("esp32-06", "humidite_sol", "z1-A1")
    assert len(rows(sessions, m.Capteur)) == declared + 1
    with sessions() as s:
        cap = s.get(m.Capteur, cid)
        assert (cap.zone, cap.emplacement, cap.materiel) == ("z1", "z1-A1", None)
        links = s.scalars(
            select(m.CapteurEmplacement.emplacement_id).where(
                m.CapteurEmplacement.capteur_id == cid
            )
        ).all()
        assert links == ["z1-A1"]
        seeded = s.get(m.Capteur, capteur_id("esp32-02", "humidite_sol", "z1-A1"))
        assert seeded.modele == "capacitif-sol"  # the declared channel is kept as is
    assert len(rows(sessions, m.Mesure)) == 6


def test_decision_is_upserted_on_status_change():
    ing, sessions = ingestor()
    send(ing, decision_topic("z1"), decision("creee"))
    ing.flush()
    send(ing, decision_topic("z1"), decision("executee"))
    ing.close()
    (dec,) = rows(sessions, m.Decision)
    assert dec.statut == "executee"


def test_invalid_messages_are_counted_not_raised():
    ing, sessions = ingestor()
    ing.on_message("serre/z1/capteur/temperature", b'{"valeur": "chaud"}')
    ing.on_message("serre/z1/cmd/pompe_nutri", encode(Command(ts=T0, action="on", source="x")))
    ing.on_message("pas/un/topic", b"{}")
    ing.on_message("serre/esp32-01/status", b"peut-etre")
    ing.close()
    assert ing.rejets == 4 and ing.recus == 0
    assert rows(sessions, m.Commande) == []


def test_duplicates_are_ignored():
    ing, sessions = ingestor()
    r = SensorReading(ts=T0, noeud="esp32-01", valeur=23.4, unite="°C", qualite="ok")
    for _ in range(2):  # QoS 1 redelivery, in one batch then across batches
        send(ing, sensor_topic("z1", "temperature"), r)
    ing.flush()
    send(ing, sensor_topic("z1", "temperature"), r)
    ing.close()
    assert len(rows(sessions, m.Mesure)) == 1


def test_rows_are_written_by_batch():
    ing, sessions = ingestor(batch_size=5, flush_s=3600)
    for i in range(5):
        r = SensorReading(
            ts=T0 + timedelta(seconds=i), noeud="esp32-09", valeur=20.0, unite="°C", qualite="ok"
        )
        send(ing, sensor_topic("z1", "temperature"), r)
        if i == 2:
            assert rows(sessions, m.Mesure) == [] and ing.pending == 4  # + the new capteur
    with sessions() as s:  # the 4th row reached batch_size
        assert s.scalar(select(func.count()).select_from(m.Mesure)) == 4
    assert ing.pending == 1
    ing.flush()
    assert len(rows(sessions, m.Mesure)) == 5


def test_vision_emplacement_from_camera_regions():
    regions = [("z1-A1", [0.0, 0.0, 0.5, 1.0]), ("z1-A2", [0.5, 0.0, 0.5, 1.0])]
    assert resolve_emplacement((0.6, 0.2, 0.2, 0.2), regions) == "z1-A2"
    assert resolve_emplacement((0.1, 0.2, 0.2, 0.2), regions) == "z1-A1"
    assert resolve_emplacement(None, regions) is None  # whole image, two emplacements
    assert resolve_emplacement(None, regions[:1]) == "z1-A1"
    assert resolve_emplacement((0.1, 0.1, 0.1, 0.1), []) is None
    assert resolve_emplacement((0.1, 0.1, 0.1, 0.1), [("z2-A1", None)]) == "z2-A1"


def test_vision_results_are_assigned_with_the_seeded_regions():
    ing, sessions = ingestor()

    def det(bbox):
        return Detection(
            espece="tomate", espece_conf=0.9, sante="sain", sante_conf=0.9,
            classe="tomate/sain/sain", classe_conf=0.9, bbox=bbox,
        )  # fmt: skip

    for cam, zone, dets in (
        ("cam-z1-a", "z1", [det((0.1, 0.2, 0.2, 0.3)), det((0.7, 0.2, 0.2, 0.3)), det(None)]),
        ("cam-z2-a", "z2", [det(None)]),  # one visible emplacement, no region
    ):
        v = VisionResult(
            ts=T0, camera=cam, image_id=f"{cam}-1", modele="clf-v1", detections=dets,
            score_anomalie=0.1, surface_verte_px=100,
        )  # fmt: skip
        send(ing, vision_topic(zone, cam), v)
    ing.close()
    got = {(r.camera, r.idx): r.emplacement_id for r in rows(sessions, m.VisionResultat)}
    assert got == {
        ("cam-z1-a", 0): "z1-A1",
        ("cam-z1-a", 1): "z1-A2",
        ("cam-z1-a", 2): None,
        ("cam-z2-a", 0): "z2-A1",
    }
