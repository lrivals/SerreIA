"""Proposals of the rules and the Decision records that precede every command (docs/10).

A rule (safety, regulation, risk, forecast, vision) returns `Proposal`s: the orders it wants
on actuators, the captures and plant health states it asks for, an optional alert, its
evidence and a deterministic explanation. The controller arbitrates them, checks each order
with `safety.py`, then publishes the `Decision` first and the `Command`s next, with
`raison = "<decision id> | <short text>"`. A proposal with `validation` gives a decision
born `proposee`: nothing runs until the user (or the agent's validated proposal) answers.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from common.mqtt import (
    Actuator,
    Command,
    Decision,
    Ordre,
    PreuveCapteur,
    Preuves,
    RegleRef,
    SensorReading,
    command_raison,
    sensor_topic,
)

Action = Literal["on", "off", "pwm"]
AlertLevel = Literal["info", "warning", "critique"]
DecisionType = Literal["routine", "exceptionnelle", "securite", "manuelle"]

# Arbitration between rules wanting the same actuator.
PRIORITY = {"securite": 100, "exceptionnelle": 50, "manuelle": 60, "routine": 10}


@dataclass(frozen=True)
class Order:
    actuator: Actuator
    action: Action
    valeur: float | None = None
    duree_s: float | None = None
    texte: str = ""  # short text of Command.raison

    @property
    def is_on(self) -> bool:
        return self.action != "off"

    def label(self) -> str:
        s = f"{self.actuator} {self.action}"
        if self.valeur is not None:
            s += f" {self.valeur:g} %"
        if self.duree_s is not None:
            s += f" {self.duree_s:g} s"
        return s

    def ordre(self) -> Ordre | None:
        """None for an order the contract rejects (pump without duration…): safety refuses
        it anyway, and the decision must stay a valid message."""
        try:
            return Ordre(
                cible=f"actionneur:{self.actuator}",
                action=self.action,
                valeur=self.valeur,
                duree_s=self.duree_s,
                texte=self.texte,
            )
        except ValueError:
            return None

    @classmethod
    def of(cls, o: Ordre) -> "Order":
        return cls(Actuator(o.subject), o.action, o.valeur, o.duree_s, o.texte)


@dataclass(frozen=True)
class Consigne:
    """Temporary change of a setpoint (mildew: humidity max lowered for 72 h)."""

    nom: Literal["humidite_max"]
    delta: float
    duree_s: float

    def label(self) -> str:
        return f"{self.nom.replace('_', ' ')} {self.delta:+g} pts {self.duree_s / 3600:g} h"


@dataclass
class AlertSpec:
    niveau: AlertLevel
    message: str
    key: str  # latch: published once while the condition holds
    fin: str | None = None  # info message published when the condition ends


@dataclass
class Proposal:
    zone: str
    regle: RegleRef
    niveau: Literal[0, 1, 2, 3]
    type: DecisionType
    explication: str
    orders: list[Order] = field(default_factory=list)
    alerte: AlertSpec | None = None
    preuves: Preuves = field(default_factory=Preuves)
    emplacements: list[str] = field(default_factory=list)
    origine: str = "controller"
    captures: list[str] = field(default_factory=list)  # cameras to capture again
    plantes: list[tuple[str, str]] = field(default_factory=list)  # (emplacement, health state)
    consigne: Consigne | None = None
    validation: bool = False  # born `proposee`, waits for the user
    # Latch of the plant states, setpoint change and proposal: once while the condition
    # holds (like the alerts), so that a rejected proposal is not proposed again at once.
    key: str | None = None

    @property
    def priority(self) -> int:
        return PRIORITY[self.type] + self.niveau

    def ordres(self) -> list[Ordre]:
        """Everything the proposal asks for, as the structured orders of the decision."""
        return (
            [o for o in map(Order.ordre, self.orders) if o is not None]
            + [Ordre(cible=f"camera:{c}", action="capture") for c in self.captures]
            + [Ordre(cible=f"plante:{e}", action=etat) for e, etat in self.plantes]
        )


def rule(rule_id: str, version: int = 1) -> RegleRef:
    return RegleRef(id=rule_id, version=version)


def evidence(
    zone: str,
    sensor: str,
    r: SensorReading | None = None,
    *,
    valeur: float | None = None,
    unite: str | None = None,
    agregat: str = "derniere",
    seuil: float | None = None,
    emplacement: str | None = None,
) -> PreuveCapteur:
    """Sensor evidence: the latest reading, or an aggregate (valeur + unite) of it."""
    return PreuveCapteur(
        topic=sensor_topic(zone, sensor),
        agregat=agregat,
        valeur=round(valeur if valeur is not None else r.valeur, 3),
        unite=unite if unite is not None else (r.unite if r else ""),
        qualite=r.qualite if r else "ok",
        seuil=seuil,
        emplacement=emplacement if emplacement is not None else (r.emplacement if r else None),
    )


def fmt(x: float, nd: int = 1) -> str:
    """French decimal comma for the explanations (deterministic templates)."""
    return f"{x:.{nd}f}".replace(".", ",")


class DecisionFactory:
    """Ids `dec-YYYYMMDD-HHMM-<zone>-NNN` (counter per minute and zone)."""

    def __init__(self):
        self.counters: dict[tuple[str, str], int] = defaultdict(int)

    def new_id(self, ts: datetime, zone: str) -> str:
        minute = f"{ts:%Y%m%d-%H%M}"
        self.counters[(minute, zone)] += 1
        if len(self.counters) > 1000:  # forget old minutes
            for k in sorted(self.counters)[:-100]:
                del self.counters[k]
        return f"dec-{minute}-{zone}-{self.counters[(minute, zone)]:03d}"

    def decision(
        self,
        p: Proposal,
        ts: datetime,
        config_version: int,
        actions: list[str],
        statut: str,
        explication: str | None = None,
        ordres: list[Ordre] | None = None,
        expire: datetime | None = None,
    ) -> Decision:
        return Decision(
            id=self.new_id(ts, p.zone),
            ts=ts,
            zone=p.zone,
            emplacements=p.emplacements,
            niveau=p.niveau,
            origine=p.origine,
            regle=p.regle,
            type=p.type,
            config_version=config_version,
            preuves=p.preuves,
            explication=explication or p.explication,
            actions=actions,
            ordres=p.ordres() if ordres is None else ordres,
            statut=statut,
            expire=expire,
        )

    @staticmethod
    def command(order: Order, decision: Decision, ts: datetime, source: str) -> Command:
        """The `Command` of one order, its `raison` pointing to the decision."""
        return Command(
            ts=ts,
            action=order.action,
            valeur=order.valeur,
            duree_s=order.duree_s,
            source=source,
            raison=command_raison(decision.id, order.texte or decision.regle.id),
        )
