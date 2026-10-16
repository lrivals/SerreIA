"""MQTT topics of the contract (docs/01-architecture.md §2)."""

import re
from dataclasses import dataclass
from enum import StrEnum

ROOT = "serre"
_ZONE_RE = re.compile(r"^z\d+$")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
CAPTURE = "capture"  # serre/<zone>/cmd/capture: on-demand capture, not an actuator (docs/05 §3)


class SensorType(StrEnum):
    TEMPERATURE = "temperature"
    HUMIDITE = "humidite"
    CO2 = "co2"
    LUX = "lux"
    PH = "ph"
    EC = "ec"
    TEMP_EAU = "temp_eau"
    NIVEAU_CUVE = "niveau_cuve"
    PRESSION = "pression"  # hPa, BMP280
    PRESENCE = "presence"  # number of radar targets 0-3, HLK-LD2450
    HUMIDITE_SOL = "humidite_sol"  # %, capacitive probes (one reading per emplacement)


class Actuator(StrEnum):
    POMPE_NUTRI = "pompe_nutri"
    POMPE_PH_DOWN = "pompe_ph_down"
    POMPE_NUTRI_A = "pompe_nutri_a"  # dosing pumps of the nutrient solution (EC)
    POMPE_NUTRI_B = "pompe_nutri_b"
    VENTILO = "ventilo"
    LED = "led"
    BRUMISATEUR = "brumisateur"
    CHAUFFAGE = "chauffage"

    @property
    def is_pump(self) -> bool:
        return self.value.startswith("pompe_")

    @property
    def is_dosing(self) -> bool:
        """Dosing pumps of the nutrient solution: inputs in mL, not water (docs/09 §5)."""
        return self in (Actuator.POMPE_PH_DOWN, Actuator.POMPE_NUTRI_A, Actuator.POMPE_NUTRI_B)


class TopicKind(StrEnum):
    CAPTEUR = "capteur"
    VISION = "vision"
    ALERTE = "alerte"
    CMD = "cmd"
    ETAT = "etat"
    STATUS = "status"
    DECISION = "decision"


@dataclass(frozen=True)
class TopicPolicy:
    qos: int
    retain: bool


TOPIC_POLICY: dict[TopicKind, TopicPolicy] = {
    TopicKind.CAPTEUR: TopicPolicy(qos=0, retain=False),
    TopicKind.VISION: TopicPolicy(qos=1, retain=False),
    TopicKind.ALERTE: TopicPolicy(qos=1, retain=False),
    TopicKind.CMD: TopicPolicy(qos=1, retain=False),
    TopicKind.ETAT: TopicPolicy(qos=1, retain=True),
    TopicKind.STATUS: TopicPolicy(qos=1, retain=True),
    TopicKind.DECISION: TopicPolicy(qos=1, retain=False),
}

SUBSCRIPTIONS: dict[TopicKind, str] = {
    TopicKind.CAPTEUR: f"{ROOT}/+/capteur/+",
    TopicKind.VISION: f"{ROOT}/+/vision/+",
    TopicKind.ALERTE: f"{ROOT}/+/alerte",
    TopicKind.CMD: f"{ROOT}/+/cmd/+",
    TopicKind.ETAT: f"{ROOT}/+/etat/+",
    TopicKind.STATUS: f"{ROOT}/+/status",
    TopicKind.DECISION: f"{ROOT}/+/decision",
}


@dataclass(frozen=True)
class ParsedTopic:
    kind: TopicKind
    scope: str  # zone (z1, z2…) or node id for status
    subject: str | None = None  # sensor type, camera id or actuator


def _check_zone(zone: str) -> str:
    if not _ZONE_RE.match(zone):
        raise ValueError(f"invalid zone {zone!r} (expected z1, z2…)")
    return zone


def _check_id(value: str, what: str) -> str:
    if not _ID_RE.match(value):
        raise ValueError(f"invalid {what} {value!r}")
    return value


def sensor_topic(zone: str, sensor: SensorType | str) -> str:
    return f"{ROOT}/{_check_zone(zone)}/capteur/{SensorType(sensor)}"


def vision_topic(zone: str, camera_id: str) -> str:
    return f"{ROOT}/{_check_zone(zone)}/vision/{_check_id(camera_id, 'camera id')}"


def alert_topic(zone: str) -> str:
    return f"{ROOT}/{_check_zone(zone)}/alerte"


def cmd_topic(zone: str, actuator: Actuator | str) -> str:
    return f"{ROOT}/{_check_zone(zone)}/cmd/{Actuator(actuator)}"


def capture_topic(zone: str) -> str:
    return f"{ROOT}/{_check_zone(zone)}/cmd/{CAPTURE}"


def state_topic(zone: str, actuator: Actuator | str) -> str:
    return f"{ROOT}/{_check_zone(zone)}/etat/{Actuator(actuator)}"


def decision_topic(zone: str) -> str:
    return f"{ROOT}/{_check_zone(zone)}/decision"


def status_topic(node: str) -> str:
    return f"{ROOT}/{_check_id(node, 'node id')}/status"


def parse_topic(topic: str) -> ParsedTopic:
    """Parse and validate a contract topic; raise ValueError if it is not one."""
    parts = topic.split("/")
    if len(parts) < 3 or parts[0] != ROOT:
        raise ValueError(f"not a contract topic: {topic!r}")

    if len(parts) == 3:
        scope, kind = parts[1], parts[2]
        if kind == TopicKind.STATUS:
            return ParsedTopic(TopicKind.STATUS, _check_id(scope, "node id"))
        if kind in (TopicKind.ALERTE, TopicKind.DECISION):
            return ParsedTopic(TopicKind(kind), _check_zone(scope))
        raise ValueError(f"not a contract topic: {topic!r}")

    if len(parts) != 4:
        raise ValueError(f"not a contract topic: {topic!r}")
    zone, kind, subject = _check_zone(parts[1]), parts[2], parts[3]
    match kind:
        case TopicKind.CAPTEUR:
            return ParsedTopic(TopicKind.CAPTEUR, zone, SensorType(subject).value)
        case TopicKind.VISION:
            return ParsedTopic(TopicKind.VISION, zone, _check_id(subject, "camera id"))
        case TopicKind.CMD if subject == CAPTURE:
            return ParsedTopic(TopicKind.CMD, zone, CAPTURE)
        case TopicKind.CMD | TopicKind.ETAT:
            return ParsedTopic(TopicKind(kind), zone, Actuator(subject).value)
    raise ValueError(f"not a contract topic: {topic!r}")
