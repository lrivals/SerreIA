"""JSON payloads of the MQTT contract (docs/01-architecture.md §2)."""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from .topics import CAPTURE, Actuator, TopicKind, parse_topic

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
Unit = Annotated[float, Field(ge=0.0, le=1.0)]


class _Message(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ts: AwareDatetime


Qualite = Literal["ok", "suspect", "erreur"]


class SensorReading(_Message):
    noeud: str
    valeur: float
    unite: str
    qualite: Qualite
    # Soil probes: several readings of one type per zone, one per emplacement (docs/09 §2).
    emplacement: str | None = None


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


class _Part(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RegleRef(_Part):
    id: str  # stable rule id, e.g. "climat.temperature.ventilation"
    version: int = Field(ge=1)


class PreuveCapteur(_Part):
    """Raw measurement or aggregate actually used by the rule (docs/10 §2)."""

    topic: str
    agregat: str = "derniere"  # derniere | moyenne_12h | duree_au_dessus | dli_jour…
    valeur: float
    unite: str
    qualite: Qualite = "ok"
    seuil: float | None = None
    emplacement: str | None = None


class PreuveVision(_Part):
    camera: str
    image_id: str
    modele: str
    classe: str
    classe_conf: Confidence
    sante: Literal["sain", "anormal"]
    sante_conf: Confidence
    espece: str | None = None
    espece_conf: Confidence | None = None
    bbox: tuple[Unit, Unit, Unit, Unit] | None = None
    score_anomalie: Confidence | None = None
    emplacement: str | None = None
    confirmations: int = Field(default=1, ge=1)


class PreuvePrevision(_Part):
    grandeur: str
    horizon: str  # "+1h", "+6h"
    valeur: float
    modele: str


class Preuves(_Part):
    vision: list[PreuveVision] = Field(default_factory=list)
    capteurs: list[PreuveCapteur] = Field(default_factory=list)
    prevision: list[PreuvePrevision] = Field(default_factory=list)
    consignes: dict[str, Any] = Field(default_factory=dict)


SanteEtat = Literal["sain", "a_surveiller", "malade", "isolee", "retiree"]
ACTIONNEUR, CAMERA, PLANTE = "actionneur", "camera", "plante"


class Ordre(_Part):
    """Structured order of a decision (docs/10 §3): what runs once the decision is executed.

    `cible`: "actionneur:<Actuator>" (action on | off | pwm, the future `Command`),
    "camera:<id>" (action "capture", a `CaptureRequest`) or "plante:<emplacement>"
    (action = new health state of the plant, applied by the server: not an MQTT command).
    """

    cible: str = Field(pattern=r"^(actionneur|camera|plante):[A-Za-z0-9_-]+$")
    action: str
    valeur: float | None = Field(default=None, ge=0, le=100)
    duree_s: float | None = Field(default=None, gt=0)
    texte: str = ""  # short text of Command.raison

    @property
    def kind(self) -> str:
        return self.cible.partition(":")[0]

    @property
    def subject(self) -> str:
        return self.cible.partition(":")[2]

    @model_validator(mode="after")
    def _check(self) -> "Ordre":
        if self.kind == ACTIONNEUR:
            Actuator(self.subject)  # ValueError for an unknown actuator
            Command(ts=_EPOCH, action=self.action, valeur=self.valeur, duree_s=self.duree_s,
                    source="ordre").validate_for(self.subject)  # fmt: skip
        elif self.kind == CAMERA:
            if self.action != "capture":
                raise ValueError("une cible camera n'accepte que l'action 'capture'")
        elif self.action not in SanteEtat.__args__:
            raise ValueError(f"état de plante inconnu {self.action!r}")
        return self

    def label(self) -> str:
        """Label: "ventilo on 900 s", "capture cam-z1-a", "plante z1-A1 malade"."""
        if self.kind == CAMERA:
            return f"capture {self.subject}"
        if self.kind == PLANTE:
            return f"plante {self.subject} {self.action}"
        s = f"{self.subject} {self.action}"
        if self.valeur is not None:
            s += f" {self.valeur:g} %"
        if self.duree_s is not None:
            s += f" {self.duree_s:g} s"
        return s


DecisionStatut = Literal[
    "proposee",
    "validee",
    "rejetee",
    "expiree",
    "creee",
    "executee",
    "terminee",
    "bloquee_securite",
]


class Decision(_Message):
    """Why a command or an alert was issued (docs/10 §2), published on serre/<zone>/decision."""

    id: str = Field(pattern=r"^dec-[A-Za-z0-9_-]+$")
    zone: str
    emplacements: list[str] = Field(default_factory=list)
    niveau: Literal[0, 1, 2, 3, "agent", "manuel"]
    origine: str  # controller | safety | agent | ui:<utilisateur>
    regle: RegleRef
    type: Literal["routine", "exceptionnelle", "securite", "manuelle"]
    config_version: int | None = None
    preuves: Preuves = Field(default_factory=Preuves)
    explication: str
    # Outcome labels: "cmd:ventilo on 900 s", "alerte", "bloquee:… (limite)", "capture:cam-z1-a",
    # "plante:z1-A1 malade", "consigne:…", "proposee:<label of an ordre>" (docs/10 §3).
    actions: list[str] = Field(default_factory=list)
    ordres: list[Ordre] = Field(default_factory=list)  # what runs once the decision executes
    statut: DecisionStatut = "creee"
    expire: AwareDatetime | None = None  # a `proposee` decision expires (docs/10 §4)


RAISON_SEP = " | "


def command_raison(decision_id: str, texte: str) -> str:
    """`Command.raison` convention: "<decision_id> | <texte court>" (docs/10 §7)."""
    return f"{decision_id}{RAISON_SEP}{texte}"


def parse_raison(raison: str | None) -> tuple[str | None, str | None]:
    """(decision id, text) of a `Command.raison`; id None for a free-text reason."""
    if raison is None:
        return None, None
    head, sep, tail = raison.partition(RAISON_SEP)
    if sep and head.startswith("dec-"):
        return head, tail
    return None, raison


NodeStatus = Literal["online", "offline"]

_SCHEMAS: dict[TopicKind, type[_Message]] = {
    TopicKind.CAPTEUR: SensorReading,
    TopicKind.VISION: VisionResult,
    TopicKind.ALERTE: Alert,
    TopicKind.CMD: Command,
    TopicKind.ETAT: ActuatorState,
    TopicKind.DECISION: Decision,
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
    "Decision",
    "Detection",
    "NodeStatus",
    "Ordre",
    "PreuveCapteur",
    "PreuvePrevision",
    "PreuveVision",
    "Preuves",
    "RegleRef",
    "SanteEtat",
    "SensorReading",
    "VisionResult",
    "command_raison",
    "decode",
    "encode",
    "parse_raison",
]
