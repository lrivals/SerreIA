"""Tables of the greenhouse model (docs/09 §7): configuration and time series.

Configuration tables are classic relational tables. Time series (`mesure`,
`vision_resultat`, `etat_actionneur`, `commande`, `alerte`, `noeud_status`) have `ts` in
their primary key so that they become TimescaleDB hypertables (`timescale.sql`); they
carry no foreign key, so that ingestion never rejects a message because the
configuration is late. Types stay portable: the tests run on SQLite.
"""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

Json = JSON().with_variant(JSONB(), "postgresql")
Ts = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


# --- configuration -------------------------------------------------------------------


class Serre(Base):
    __tablename__ = "serre"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    nom: Mapped[str] = mapped_column(String(128))
    fuseau: Mapped[str] = mapped_column(String(64), default="Europe/Paris")
    tarif_kwh: Mapped[float | None] = mapped_column(Float)
    lux_vers_ppfd: Mapped[float] = mapped_column(Float, default=0.0185)
    config_version: Mapped[int] = mapped_column(Integer, default=0)
    # Controller parameters of serre.yaml (hysteresis, securite, risque, lumiere, prevision).
    parametres: Mapped[dict | None] = mapped_column(Json)


class Cuve(Base):
    __tablename__ = "cuve"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    serre_id: Mapped[str] = mapped_column(ForeignKey("serre.id"))
    volume_l: Mapped[float | None] = mapped_column(Float)
    # Placement in the game view (docs/13 §3): purely visual, not exported to serre.yaml.
    disposition: Mapped[dict | None] = mapped_column(Json)


class Zone(Base):
    __tablename__ = "zone"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # z1, z2… (MQTT segment)
    serre_id: Mapped[str] = mapped_column(ForeignKey("serre.id"))
    nom: Mapped[str] = mapped_column(String(128), default="")
    cuve_id: Mapped[str | None] = mapped_column(ForeignKey("cuve.id"))
    jour_debut: Mapped[str] = mapped_column(String(5), default="06:00")  # local time
    presence_autorisee: Mapped[list | None] = mapped_column(Json)  # [{debut, fin}]
    # Placement in the game view (docs/13 §3): purely visual, not exported to serre.yaml.
    disposition: Mapped[dict | None] = mapped_column(Json)


class Contenant(Base):
    __tablename__ = "contenant"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(32))  # pot, jardiniere, canal_NFT…
    volume_l: Mapped[float | None] = mapped_column(Float)
    materiau: Mapped[str | None] = mapped_column(String(32))
    drainage: Mapped[bool | None] = mapped_column(Boolean)


class Emplacement(Base):
    __tablename__ = "emplacement"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # z1-A1
    zone_id: Mapped[str] = mapped_column(ForeignKey("zone.id"))
    code: Mapped[str] = mapped_column(String(16))  # A1
    mode_culture: Mapped[str] = mapped_column(String(16))
    rangee: Mapped[int | None] = mapped_column(Integer)
    colonne: Mapped[int | None] = mapped_column(Integer)
    contenant_id: Mapped[int | None] = mapped_column(ForeignKey("contenant.id"))
    # Placement in the game view (docs/13 §3): purely visual, not exported to serre.yaml.
    disposition: Mapped[dict | None] = mapped_column(Json)


class Recette(Base):
    __tablename__ = "recette"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    espece: Mapped[str] = mapped_column(String(64))
    stades: Mapped[dict] = mapped_column(Json)  # same structure as recettes.yaml


class Plante(Base):
    __tablename__ = "plante"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    espece: Mapped[str] = mapped_column(String(64))
    variete: Mapped[str | None] = mapped_column(String(128))
    date_semis: Mapped[date | None] = mapped_column(Date)
    date_plantation: Mapped[date | None] = mapped_column(Date)
    stade: Mapped[str] = mapped_column(String(16))
    recette_id: Mapped[str | None] = mapped_column(ForeignKey("recette.id"))
    etat_sante: Mapped[str] = mapped_column(String(16), default="sain")
    prioritaire: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)


class Affectation(Base):
    """A plant on an emplacement from `debut` to `fin` (None: current); moving a plant
    closes the assignment and opens a new one (docs/09 §1)."""

    __tablename__ = "affectation"
    __table_args__ = (
        Index(
            "uq_affectation_active",
            "emplacement_id",
            unique=True,
            postgresql_where=text("fin IS NULL"),
            sqlite_where=text("fin IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plante_id: Mapped[str] = mapped_column(ForeignKey("plante.id"))
    emplacement_id: Mapped[str] = mapped_column(ForeignKey("emplacement.id"))
    debut: Mapped[datetime] = mapped_column(Ts)
    fin: Mapped[datetime | None] = mapped_column(Ts)


class Capteur(Base):
    """One measurement channel (node × type × emplacement), registered by the ingestion
    on its first message; model and calibration are filled in from the UI (G2)."""

    __tablename__ = "capteur"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)  # esp32-01-temperature
    materiel: Mapped[str | None] = mapped_column(String(64))  # declared device (sht41-z1)
    noeud: Mapped[str] = mapped_column(String(64))
    zone: Mapped[str] = mapped_column(String(16), index=True)
    type: Mapped[str] = mapped_column(String(32))  # SensorType
    emplacement: Mapped[str | None] = mapped_column(String(32))  # soil probes
    modele: Mapped[str | None] = mapped_column(String(32))
    cuve_id: Mapped[str | None] = mapped_column(String(64))
    etalonnage: Mapped[dict | None] = mapped_column(Json)
    plage_min: Mapped[float | None] = mapped_column(Float)
    plage_max: Mapped[float | None] = mapped_column(Float)
    # Placement in the game view (docs/13 §3): purely visual, not exported to serre.yaml.
    disposition: Mapped[dict | None] = mapped_column(Json)


class CapteurEmplacement(Base):
    __tablename__ = "capteur_emplacement"

    capteur_id: Mapped[str] = mapped_column(ForeignKey("capteur.id"), primary_key=True)
    emplacement_id: Mapped[str] = mapped_column(ForeignKey("emplacement.id"), primary_key=True)


class Actionneur(Base):
    __tablename__ = "actionneur"
    __table_args__ = (Index("uq_actionneur_zone_type", "zone_id", "type", unique=True),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    zone_id: Mapped[str] = mapped_column(ForeignKey("zone.id"))
    type: Mapped[str] = mapped_column(String(32))  # Actuator (topic segment)
    noeud: Mapped[str] = mapped_column(String(64))
    commande: Mapped[str] = mapped_column(String(8), default="on_off")
    puissance_w: Mapped[float | None] = mapped_column(Float)
    debit_l_h: Mapped[float | None] = mapped_column(Float)
    debit_ml_min: Mapped[float | None] = mapped_column(Float)  # dosing pumps
    ppfd_max: Mapped[float | None] = mapped_column(Float)
    duree_max_s: Mapped[float | None] = mapped_column(Float)
    # Controller timings of serre.yaml (duree_s, impulsion_s, melange_s, delai_min_s…).
    parametres: Mapped[dict | None] = mapped_column(Json)
    # Placement in the game view (docs/13 §3): purely visual, not exported to serre.yaml.
    disposition: Mapped[dict | None] = mapped_column(Json)


class Camera(Base):
    __tablename__ = "camera"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    zone_id: Mapped[str] = mapped_column(ForeignKey("zone.id"))
    # Placement in the game view (docs/13 §3): purely visual, not exported to serre.yaml.
    disposition: Mapped[dict | None] = mapped_column(Json)


class ConfigExport(Base):
    """One exported version of serre.yaml (docs/09 §8): decisions record the
    `config_version` they ran with, this table gives back its exact content."""

    __tablename__ = "config_export"

    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(Ts)
    sha256: Mapped[str] = mapped_column(String(64))  # of the content without the version
    contenu: Mapped[dict] = mapped_column(Json)


class CameraRegion(Base):
    __tablename__ = "camera_region"

    camera_id: Mapped[str] = mapped_column(ForeignKey("camera.id"), primary_key=True)
    emplacement_id: Mapped[str] = mapped_column(ForeignKey("emplacement.id"), primary_key=True)
    # [x, y, w, h] normalised to [0, 1]; None: visible emplacement without a region.
    bbox: Mapped[list | None] = mapped_column(Json)


# --- time series (hypertables) -------------------------------------------------------


class Mesure(Base):
    __tablename__ = "mesure"
    __table_args__ = (Index("ix_mesure_zone_type_ts", "zone", "type", "ts"),)

    ts: Mapped[datetime] = mapped_column(Ts, primary_key=True)
    capteur_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    zone: Mapped[str] = mapped_column(String(16))
    type: Mapped[str] = mapped_column(String(32))
    noeud: Mapped[str] = mapped_column(String(64))
    emplacement: Mapped[str | None] = mapped_column(String(32))
    valeur: Mapped[float] = mapped_column(Float)
    unite: Mapped[str] = mapped_column(String(16))
    qualite: Mapped[str] = mapped_column(String(8))


class VisionResultat(Base):
    """One row per `Detection` of a `VisionResult`."""

    __tablename__ = "vision_resultat"
    __table_args__ = (Index("ix_vision_zone_ts", "zone", "ts"),)

    ts: Mapped[datetime] = mapped_column(Ts, primary_key=True)
    image_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    idx: Mapped[int] = mapped_column(Integer, primary_key=True)  # index of the detection
    zone: Mapped[str] = mapped_column(String(16))
    camera: Mapped[str] = mapped_column(String(64))
    emplacement_id: Mapped[str | None] = mapped_column(String(32))
    modele: Mapped[str] = mapped_column(String(64))
    espece: Mapped[str] = mapped_column(String(64))
    espece_conf: Mapped[float] = mapped_column(Float)
    sante: Mapped[str] = mapped_column(String(8))
    sante_conf: Mapped[float] = mapped_column(Float)
    classe: Mapped[str] = mapped_column(String(128))
    classe_conf: Mapped[float] = mapped_column(Float)
    bbox: Mapped[list | None] = mapped_column(Json)
    score_anomalie: Mapped[float] = mapped_column(Float)
    surface_verte_px: Mapped[int] = mapped_column(Integer)


class EtatActionneur(Base):
    __tablename__ = "etat_actionneur"

    ts: Mapped[datetime] = mapped_column(Ts, primary_key=True)
    zone: Mapped[str] = mapped_column(String(16), primary_key=True)
    actionneur: Mapped[str] = mapped_column(String(32), primary_key=True)  # Actuator
    actionneur_id: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(8))
    valeur: Mapped[float | None] = mapped_column(Float)


class Commande(Base):
    __tablename__ = "commande"

    ts: Mapped[datetime] = mapped_column(Ts, primary_key=True)
    zone: Mapped[str] = mapped_column(String(16), primary_key=True)
    actionneur: Mapped[str] = mapped_column(String(32), primary_key=True)  # or "capture"
    action: Mapped[str] = mapped_column(String(8))  # on | off | pwm | capture
    valeur: Mapped[float | None] = mapped_column(Float)
    duree_s: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(64))
    raison: Mapped[str | None] = mapped_column(Text)
    decision_id: Mapped[str | None] = mapped_column(String(64), index=True)
    camera: Mapped[str | None] = mapped_column(String(64))  # capture requests


class Alerte(Base):
    __tablename__ = "alerte"

    ts: Mapped[datetime] = mapped_column(Ts, primary_key=True)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    zone: Mapped[str] = mapped_column(String(16))
    niveau: Mapped[str] = mapped_column(String(8))
    message: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(64))
    acquittee: Mapped[bool] = mapped_column(Boolean, default=False)


class NoeudStatus(Base):
    """`serre/<noeud>/status` carries no timestamp: `ts` is the reception time."""

    __tablename__ = "noeud_status"

    ts: Mapped[datetime] = mapped_column(Ts, primary_key=True)
    noeud: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(8))


class Decision(Base):
    """`Decision` of the MQTT contract (docs/10 §2), upserted by id: a decision changes
    status (proposee → validee → executee → terminee…). Not a hypertable (updated rows)."""

    __tablename__ = "decision"
    __table_args__ = (Index("ix_decision_zone_ts", "zone", "ts"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ts: Mapped[datetime] = mapped_column(Ts)
    zone: Mapped[str] = mapped_column(String(16))
    emplacements: Mapped[list] = mapped_column(Json)
    niveau: Mapped[str] = mapped_column(String(8))  # 0-3, agent, manuel
    origine: Mapped[str] = mapped_column(String(64))
    regle_id: Mapped[str] = mapped_column(String(128))
    regle_version: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(16))
    config_version: Mapped[int | None] = mapped_column(Integer)
    preuves: Mapped[dict] = mapped_column(Json)
    explication: Mapped[str] = mapped_column(Text)
    actions: Mapped[list] = mapped_column(Json)
    ordres: Mapped[list | None] = mapped_column(Json)
    statut: Mapped[str] = mapped_column(String(16))
    expire: Mapped[datetime | None] = mapped_column(Ts)


class Action(Base):
    """One action of a decision (docs/10 §3), derived by `backend/traceability.py` from
    the labels of the decision and the commands that point to it (`Command.raison`).
    `resultat`: en_attente | confirmee | non_confirmee | bloquee | echec | proposee |
    annulee (a proposal expired or rejected)."""

    __tablename__ = "action"
    __table_args__ = (Index("ix_action_zone_ts", "zone", "ts_debut"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)  # act-<decision>-NN
    decision_id: Mapped[str] = mapped_column(String(64), index=True)
    zone: Mapped[str] = mapped_column(String(16))
    type: Mapped[str] = mapped_column(String(16))  # routine | exceptionnelle | securite | manuelle
    cible: Mapped[str] = mapped_column(String(64))  # actionneur:ventilo, alerte, camera:…, plante:…
    label: Mapped[str] = mapped_column(Text)
    commande: Mapped[dict | None] = mapped_column(Json)  # the Command, as published
    resultat: Mapped[str] = mapped_column(String(16))
    ts_debut: Mapped[datetime] = mapped_column(Ts)
    ts_fin: Mapped[datetime | None] = mapped_column(Ts)


# --- daily aggregates (backend/consumption.py) ---------------------------------------


class ConsommationJour(Base):
    """Estimated consumption of one actuator over one local day (docs/09 §5)."""

    __tablename__ = "consommation_jour"

    jour: Mapped[date] = mapped_column(Date, primary_key=True)
    actionneur_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    zone: Mapped[str] = mapped_column(String(16))
    type: Mapped[str] = mapped_column(String(32))
    duree_on_s: Mapped[float] = mapped_column(Float)  # weighted by the PWM duty cycle
    kwh: Mapped[float | None] = mapped_column(Float)
    litres: Mapped[float | None] = mapped_column(Float)
    ml: Mapped[float | None] = mapped_column(Float)  # dosing pumps: inputs (pH−, A, B)
    dli: Mapped[float | None] = mapped_column(Float)  # LED only, mol/m²/day
    cout: Mapped[float | None] = mapped_column(Float)


class LumiereJour(Base):
    """Daily light integral of a zone: measured (lux sensor, LED included) and LED part."""

    __tablename__ = "lumiere_jour"

    jour: Mapped[date] = mapped_column(Date, primary_key=True)
    zone: Mapped[str] = mapped_column(String(16), primary_key=True)
    dli_total: Mapped[float | None] = mapped_column(Float)
    dli_led: Mapped[float] = mapped_column(Float)
    dli_naturel: Mapped[float | None] = mapped_column(Float)
    couverture: Mapped[float] = mapped_column(Float)  # share of the day covered by lux data


# --- conversational agent (docs/11) ----------------------------------------------------


class AgentConversation(Base):
    """One conversation with the agent; `messages` is the history in the format of the
    Claude API (content blocks as returned, thinking included), replayed at each turn."""

    __tablename__ = "agent_conversation"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # conv-<hex>
    ts_debut: Mapped[datetime] = mapped_column(Ts)
    ts_maj: Mapped[datetime] = mapped_column(Ts)
    utilisateur: Mapped[str] = mapped_column(String(64))
    modele: Mapped[str] = mapped_column(String(64))
    titre: Mapped[str] = mapped_column(Text, default="")
    messages: Mapped[list] = mapped_column(Json)


class AgentJournal(Base):
    """Full log of the agent (docs/11 §4.6): messages, tool calls with their arguments and
    results, model and tokens of each API call. `type`: utilisateur | assistant |
    appel_outil | resultat_outil | erreur."""

    __tablename__ = "agent_journal"
    __table_args__ = (Index("ix_agent_journal_conv_ts", "conversation_id", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(40))
    ts: Mapped[datetime] = mapped_column(Ts, index=True)
    type: Mapped[str] = mapped_column(String(16))
    contenu: Mapped[dict] = mapped_column(Json)
    modele: Mapped[str | None] = mapped_column(String(64))
    tokens_entree: Mapped[int] = mapped_column(Integer, default=0)
    tokens_sortie: Mapped[int] = mapped_column(Integer, default=0)
    tokens_cache_lus: Mapped[int] = mapped_column(Integer, default=0)
    tokens_cache_ecrits: Mapped[int] = mapped_column(Integer, default=0)


class AgentProposition(Base):
    """What the agent proposed with a decision (docs/11 §3): its justification and
    references, and for `proposer_consigne` the recipe change, applied by the server on
    validation (`backend/agent/consignes.py`): previous value, end of a temporary change."""

    __tablename__ = "agent_proposition"

    decision_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str | None] = mapped_column(String(40), index=True)
    outil: Mapped[str] = mapped_column(String(32))
    justification: Mapped[str] = mapped_column(Text)
    preuves_refs: Mapped[list] = mapped_column(Json)
    # {recette_id, stade, grandeur, valeur, duree_h}
    consigne: Mapped[dict | None] = mapped_column(Json)
    ancienne: Mapped[dict | None] = mapped_column(Json)  # {"valeur": …} before the change
    appliquee: Mapped[datetime | None] = mapped_column(Ts)
    fin: Mapped[datetime | None] = mapped_column(Ts)  # temporary change: restored at `fin`
    restauree: Mapped[datetime | None] = mapped_column(Ts)
