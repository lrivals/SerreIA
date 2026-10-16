"""MQTT contract: payload and topic formats (docs/01-architecture.md §2)."""

import json

import pytest
from pydantic import ValidationError

from common.mqtt import (
    TOPIC_POLICY,
    Actuator,
    CaptureRequest,
    Command,
    Decision,
    Ordre,
    SensorReading,
    SensorType,
    TopicKind,
    VisionResult,
    alert_topic,
    capture_topic,
    cmd_topic,
    command_raison,
    decision_topic,
    decode,
    encode,
    parse_raison,
    parse_topic,
    sensor_topic,
    state_topic,
    status_topic,
    vision_topic,
)

# Examples copied from docs/01-architecture.md.
SENSOR_EXAMPLE = {
    "ts": "2026-10-12T14:03:00Z",
    "noeud": "esp32-01",
    "valeur": 23.4,
    "unite": "°C",
    "qualite": "ok",
}
VISION_EXAMPLE = {
    "ts": "2026-10-12T14:00:00Z",
    "camera": "cam-z1-a",
    "image_id": "z1-a-20261012T140000",
    "modele": "clf-effb0-v3",
    "detections": [
        {
            "bbox": [0.12, 0.30, 0.25, 0.22],
            "espece": "tomate",
            "espece_conf": 0.97,
            "sante": "anormal",
            "sante_conf": 0.88,
            "classe": "tomate/maladie/septoriose",
            "classe_conf": 0.74,
        }
    ],
    "score_anomalie": 0.31,
    "surface_verte_px": 184233,
}
COMMAND_EXAMPLE = {
    "ts": "2026-10-12T14:05:00Z",
    "action": "on",
    "duree_s": 30,
    "source": "controller",
    "raison": "pH 6.9 > consigne 6.2",
}


def with_(base: dict, **changes) -> dict:
    return {**base, **changes}


def detection(**changes) -> dict:
    return with_(VISION_EXAMPLE, detections=[with_(VISION_EXAMPLE["detections"][0], **changes)])


# --- payloads -------------------------------------------------------------


def test_doc_examples_are_valid():
    SensorReading.model_validate(SENSOR_EXAMPLE)
    VisionResult.model_validate(VISION_EXAMPLE)
    Command.model_validate(COMMAND_EXAMPLE).validate_for(Actuator.POMPE_PH_DOWN)


def test_phase1_detection_without_bbox():
    result = VisionResult.model_validate(detection(bbox=None))
    assert result.detections[0].bbox is None


@pytest.mark.parametrize(
    "model, payload",
    [
        (SensorReading, with_(SENSOR_EXAMPLE, qualite="bof")),
        (SensorReading, with_(SENSOR_EXAMPLE, ts="2026-10-12T14:03:00")),  # no timezone
        (SensorReading, with_(SENSOR_EXAMPLE, extra=1)),
        (VisionResult, detection(classe_conf=1.2)),
        (VisionResult, detection(bbox=[0.1, 0.2, 1.5, 0.2])),
        (VisionResult, detection(bbox=[0.1, 0.2, 0.3])),
        (VisionResult, detection(sante="malade")),
        (VisionResult, with_(VISION_EXAMPLE, detections=[])),
        (VisionResult, with_(VISION_EXAMPLE, surface_verte_px=-1)),
        (Command, with_(COMMAND_EXAMPLE, action="pwm")),  # pwm without valeur
        (Command, with_(COMMAND_EXAMPLE, action="on", valeur=50)),
        (Command, with_(COMMAND_EXAMPLE, action="pwm", valeur=120)),
        (Command, with_(COMMAND_EXAMPLE, duree_s=0)),
    ],
)
def test_invalid_payloads_are_rejected(model, payload):
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_pump_on_requires_duration():
    cmd = Command.model_validate(with_(COMMAND_EXAMPLE, duree_s=None))
    with pytest.raises(ValueError, match="duree_s"):
        cmd.validate_for(Actuator.POMPE_NUTRI)
    cmd.validate_for(Actuator.VENTILO)  # non-pump actuators may run unbounded
    Command.model_validate(with_(COMMAND_EXAMPLE, action="off", duree_s=None)).validate_for(
        Actuator.POMPE_NUTRI
    )


def test_pwm_command():
    cmd = Command.model_validate(with_(COMMAND_EXAMPLE, action="pwm", valeur=40, duree_s=None))
    assert cmd.validate_for(Actuator.LED).valeur == 40


# --- encode / decode ------------------------------------------------------


@pytest.mark.parametrize(
    "topic, payload, model",
    [
        (sensor_topic("z1", SensorType.TEMPERATURE), SENSOR_EXAMPLE, SensorReading),
        (vision_topic("z1", "cam-z1-a"), VISION_EXAMPLE, VisionResult),
        (cmd_topic("z1", Actuator.POMPE_PH_DOWN), COMMAND_EXAMPLE, Command),
    ],
)
def test_roundtrip(topic, payload, model):
    message = decode(topic, json.dumps(payload).encode())
    assert isinstance(message, model)
    assert decode(topic, encode(message)) == message


def test_decode_rejects_pump_command_without_duration():
    with pytest.raises(ValueError, match="duree_s"):
        decode(cmd_topic("z1", "pompe_nutri"), json.dumps(with_(COMMAND_EXAMPLE, duree_s=None)))


def test_capture_request():
    topic = capture_topic("z1")
    assert topic == "serre/z1/cmd/capture"
    payload = {"ts": "2026-10-12T14:00:00Z", "source": "dashboard", "camera": "cam-z1-a"}
    message = decode(topic, json.dumps(payload))
    assert isinstance(message, CaptureRequest) and message.camera == "cam-z1-a"
    assert decode(topic, encode(message)) == message
    assert decode(topic, json.dumps(with_(payload, camera=None))).camera is None
    with pytest.raises(ValidationError):
        decode(topic, json.dumps(COMMAND_EXAMPLE))  # an actuator command is not a capture


def test_status_payload():
    assert decode(status_topic("esp32-01"), b"online") == "online"
    assert encode("offline") == b"offline"
    with pytest.raises(ValueError):
        decode(status_topic("esp32-01"), b"up")


# --- topics ---------------------------------------------------------------


def test_topic_builders():
    assert sensor_topic("z1", "co2") == "serre/z1/capteur/co2"
    assert vision_topic("z2", "cam-z2-a") == "serre/z2/vision/cam-z2-a"
    assert alert_topic("z1") == "serre/z1/alerte"
    assert cmd_topic("z1", Actuator.LED) == "serre/z1/cmd/led"
    assert state_topic("z1", "ventilo") == "serre/z1/etat/ventilo"
    assert status_topic("esp32-01") == "serre/esp32-01/status"


@pytest.mark.parametrize(
    "topic, kind, scope, subject",
    [
        ("serre/z1/capteur/temp_eau", TopicKind.CAPTEUR, "z1", "temp_eau"),
        ("serre/z1/vision/cam-z1-a", TopicKind.VISION, "z1", "cam-z1-a"),
        ("serre/z3/alerte", TopicKind.ALERTE, "z3", None),
        ("serre/z1/cmd/brumisateur", TopicKind.CMD, "z1", "brumisateur"),
        ("serre/z1/etat/chauffage", TopicKind.ETAT, "z1", "chauffage"),
        ("serre/z1/cmd/capture", TopicKind.CMD, "z1", "capture"),
        ("serre/esp32-02/status", TopicKind.STATUS, "esp32-02", None),
        ("serre/z1/capteur/pression", TopicKind.CAPTEUR, "z1", "pression"),
        ("serre/z1/capteur/presence", TopicKind.CAPTEUR, "z1", "presence"),
        ("serre/z1/capteur/humidite_sol", TopicKind.CAPTEUR, "z1", "humidite_sol"),
        ("serre/z2/cmd/pompe_nutri_a", TopicKind.CMD, "z2", "pompe_nutri_a"),
        ("serre/z1/decision", TopicKind.DECISION, "z1", None),
    ],
)
def test_parse_topic(topic, kind, scope, subject):
    parsed = parse_topic(topic)
    assert (parsed.kind, parsed.scope, parsed.subject) == (kind, scope, subject)


@pytest.mark.parametrize(
    "topic",
    [
        "serre/zone1/capteur/co2",  # bad zone
        "serre/z1/capteur/pluie",  # unknown sensor
        "serre/z1/cmd/arroseur",  # unknown actuator
        "serre/z1/etat/capture",  # capture is a command only
        "maison/z1/capteur/co2",
        "serre/z1/capteur",
        "serre/z1/capteur/co2/extra",
    ],
)
def test_parse_topic_rejects_invalid(topic):
    with pytest.raises(ValueError):
        parse_topic(topic)


def test_topic_policy_matches_doc():
    assert {k: (p.qos, p.retain) for k, p in TOPIC_POLICY.items()} == {
        TopicKind.CAPTEUR: (0, False),
        TopicKind.VISION: (1, False),
        TopicKind.ALERTE: (1, False),
        TopicKind.CMD: (1, False),
        TopicKind.ETAT: (1, True),
        TopicKind.STATUS: (1, True),
        TopicKind.DECISION: (1, False),
    }


# --- decisions (docs/10 §2, §7) ---------------------------------------------

DECISION_EXAMPLE = {
    "id": "dec-20261012-0231-z1-007",
    "ts": "2026-10-12T02:31:00Z",
    "zone": "z1",
    "emplacements": ["z1-A1"],
    "niveau": 1,
    "origine": "controller",
    "regle": {"id": "maladie.mildiou.ventilation", "version": 3},
    "type": "exceptionnelle",
    "config_version": 12,
    "preuves": {
        "vision": [
            {
                "image_id": "z1-a-20261012T020000", "camera": "cam-z1-a", "modele": "clf-effb0-v3",
                "emplacement": "z1-A1", "espece": "tomate", "espece_conf": 0.97,
                "sante": "anormal", "sante_conf": 0.88, "classe": "tomate/maladie/mildiou",
                "classe_conf": 0.81, "bbox": None, "score_anomalie": 0.42, "confirmations": 3,
            }
        ],
        "capteurs": [
            {"topic": "serre/z1/capteur/humidite", "agregat": "duree_au_dessus", "seuil": 90,
             "valeur": 11.2, "unite": "h", "qualite": "ok"},
        ],
        "prevision": [{"grandeur": "humidite", "horizon": "+6h", "valeur": 93, "modele": "gru-v1"}],
        "consignes": {"recette": "tomate-standard", "stade": "floraison", "humidite": [55, 70]},
    },
    "explication": "HR > 90 % depuis 11,2 h -> ventilation 15 min + alerte.",
    "actions": ["cmd:ventilo on 900 s", "alerte"],
    "statut": "executee",
}  # fmt: skip


def test_decision_roundtrip():
    topic = decision_topic("z1")
    assert topic == "serre/z1/decision"
    message = decode(topic, json.dumps(DECISION_EXAMPLE))
    assert isinstance(message, Decision) and message.preuves.vision[0].confirmations == 3
    assert decode(topic, encode(message)) == message
    with pytest.raises(ValidationError):
        Decision.model_validate(with_(DECISION_EXAMPLE, id="007"))
    with pytest.raises(ValidationError):
        Decision.model_validate(with_(DECISION_EXAMPLE, statut="faite"))


def test_proposed_decision_with_orders():
    ordres = [
        {"cible": "actionneur:ventilo", "action": "on", "duree_s": 900, "texte": "mildiou"},
        {"cible": "camera:cam-z1-a", "action": "capture"},
        {"cible": "plante:z1-A1", "action": "isolee"},
    ]
    payload = with_(DECISION_EXAMPLE, statut="proposee", ordres=ordres,
                    expire="2026-10-12T04:31:00Z",
                    actions=["proposee:ventilo on 900 s", "proposee:capture cam-z1-a",
                             "proposee:plante z1-A1 isolee"])  # fmt: skip
    message = decode(decision_topic("z1"), json.dumps(payload))
    assert [o.label() for o in message.ordres] == [
        "ventilo on 900 s", "capture cam-z1-a", "plante z1-A1 isolee"
    ]  # fmt: skip
    assert [f"proposee:{o.label()}" for o in message.ordres] == message.actions
    assert message.expire.hour == 4 and message.ordres[0].kind == "actionneur"
    for statut in ("validee", "rejetee", "expiree", "terminee"):
        assert Decision.model_validate(with_(DECISION_EXAMPLE, statut=statut)).statut == statut


@pytest.mark.parametrize(
    "ordre",
    [
        {"cible": "actionneur:pompe_nutri", "action": "on"},  # a pump must be bounded
        {"cible": "actionneur:ventilo", "action": "pwm"},  # pwm needs valeur
        {"cible": "actionneur:arroseur", "action": "on"},  # unknown actuator
        {"cible": "camera:cam-z1-a", "action": "on"},
        {"cible": "plante:z1-A1", "action": "morte"},
        {"cible": "serre:z1", "action": "on"},
    ],
)
def test_invalid_orders(ordre):
    with pytest.raises(ValidationError):
        Ordre.model_validate(ordre)


def test_command_raison_links_decision():
    raison = command_raison("dec-20261012-0231-z1-007", "ventilation mildiou")
    assert parse_raison(raison) == ("dec-20261012-0231-z1-007", "ventilation mildiou")
    assert parse_raison("pH 6.9 > consigne 6.2") == (None, "pH 6.9 > consigne 6.2")
    assert parse_raison(None) == (None, None)


def test_soil_reading_with_emplacement():
    payload = with_(SENSOR_EXAMPLE, noeud="esp32-02", valeur=41.0, unite="%", emplacement="z1-A1")
    message = decode(sensor_topic("z1", SensorType.HUMIDITE_SOL), json.dumps(payload))
    assert message.emplacement == "z1-A1"
    assert SensorReading.model_validate(SENSOR_EXAMPLE).emplacement is None


def test_nutrient_pumps_are_pumps():
    assert Actuator.POMPE_NUTRI_A.is_pump and Actuator.POMPE_NUTRI_B.is_pump
