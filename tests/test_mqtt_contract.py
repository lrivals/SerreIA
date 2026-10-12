"""MQTT contract: payload and topic formats (docs/01-architecture.md §2)."""

import json

import pytest
from pydantic import ValidationError

from common.mqtt import (
    TOPIC_POLICY,
    Actuator,
    Command,
    SensorReading,
    SensorType,
    TopicKind,
    VisionResult,
    alert_topic,
    cmd_topic,
    decode,
    encode,
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
        ("serre/esp32-02/status", TopicKind.STATUS, "esp32-02", None),
    ],
)
def test_parse_topic(topic, kind, scope, subject):
    parsed = parse_topic(topic)
    assert (parsed.kind, parsed.scope, parsed.subject) == (kind, scope, subject)


@pytest.mark.parametrize(
    "topic",
    [
        "serre/zone1/capteur/co2",  # bad zone
        "serre/z1/capteur/pression",  # unknown sensor
        "serre/z1/cmd/arroseur",  # unknown actuator
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
    }
