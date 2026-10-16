"""JSON payloads of the MQTT contract (docs/01-architecture.md §2)."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from .topics import CAPTURE, Actuator, TopicKind, parse_topic

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
Unit = Annotated[float, Field(ge=0.0, le=1.0)]


class _Message(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ts: AwareDatetime


class SensorReading(_Message):
    noeud: str
    valeur: float
    unite: str
    qualite: Literal["ok", "suspect", "erreur"]


class Detection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # (x, y, w, h) normalised to [0, 1]; None in phase 1 (whole image or tile).
    bbox: tuple[Unit, Unit, Unit, Unit] | None
    espece: str
    espece_conf: Confidence
    sante: Literal["sain", "anormal"]
    sante_conf: Confidence
    classe: str
    classe_conf: Confidence


class VisionResult(_Message):
    camera: str
    image_id: str
    modele: str
    detections: list[Detection] = Field(min_length=1)
    score_anomalie: Confidence
    surface_verte_px: int = Field(ge=0)


class Alert(_Message):
    niveau: Literal["info", "warning", "critique"]
    message: str
    source: str


class Command(_Message):
    action: Literal["on", "off", "pwm"]
    valeur: float | None = Field(default=None, ge=0, le=100)
    duree_s: float | None = Field(default=None, gt=0)
    source: str
    raison: str | None = None

    @model_validator(mode="after")
    def _check_pwm(self) -> "Command":
        if (self.action == "pwm") != (self.valeur is not None):
            raise ValueError("'valeur' is required for action 'pwm' and only for it")
        return self

    def validate_for(self, actuator: Actuator | str) -> "Command":
        """Pumps must always be bounded in time: the ESP32 cuts them at the deadline."""
        if Actuator(actuator).is_pump and self.action != "off" and self.duree_s is None:
            raise ValueError(f"'duree_s' is required for pump {actuator}")
        return self


class CaptureRequest(_Message):
    """On-demand capture (serre/<zone>/cmd/capture); camera None = every camera of the zone."""

    source: str
    camera: str | None = None


class ActuatorState(_Message):
    action: Literal["on", "off", "pwm"]
    valeur: float | None = Field(default=None, ge=0, le=100)


NodeStatus = Literal["online", "offline"]

_SCHEMAS: dict[TopicKind, type[_Message]] = {
    TopicKind.CAPTEUR: SensorReading,
    TopicKind.VISION: VisionResult,
    TopicKind.ALERTE: Alert,
    TopicKind.CMD: Command,
    TopicKind.ETAT: ActuatorState,
}


def encode(message: _Message | NodeStatus) -> bytes:
    if isinstance(message, str):
        return _check_status(message).encode()
    return message.model_dump_json(exclude_none=False).encode()


def decode(topic: str, payload: bytes | str) -> _Message | NodeStatus:
    """Validate a payload against the schema implied by its topic."""
    parsed = parse_topic(topic)
    if isinstance(payload, bytes):
        payload = payload.decode()
    if parsed.kind is TopicKind.STATUS:
        return _check_status(payload)
    if parsed.kind is TopicKind.CMD and parsed.subject == CAPTURE:
        return CaptureRequest.model_validate_json(payload)
    message = _SCHEMAS[parsed.kind].model_validate_json(payload)
    if isinstance(message, Command):
        message.validate_for(parsed.subject)
    return message


def _check_status(status: str) -> NodeStatus:
    if status not in ("online", "offline"):
        raise ValueError(f"invalid node status {status!r}")
    return status  # type: ignore[return-value]


__all__ = [
    "ActuatorState",
    "Alert",
    "CaptureRequest",
    "Command",
    "Detection",
    "NodeStatus",
    "SensorReading",
    "VisionResult",
    "decode",
    "encode",
]
