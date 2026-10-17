"""Tools of the agent (docs/11 §3): what the LLM can see of the greenhouse and propose.

The agent has no access to the database or to MQTT: only these tools. Each call runs in
its own transaction and returns compact JSON; a refusal (unknown actuator, duration over
the limit, setpoint outside the safety limits, invented reference…) comes back as an
explicit tool error, so that the LLM rephrases, and creates nothing (docs/11 §4).

- Reading: `get_serre`, `get_plante`, `get_mesures`, `get_vision`, `get_decisions`,
  `get_arbre_actions`, `get_consommation`, `get_regle`.
- Proposal: `proposer_action`, `proposer_consigne`, `proposer_etat_plante` create a
  `Decision` `niveau: agent`, `statut: proposee`, that expires (2 h); the user validates it
  with `POST /decisions/{id}/valider`, the controller then runs it through safety.py.
  `demander_capture` is the only action run at once (no effect on the plants): a decision
  born `validee`, published on `serre/<zone>/decision`. Nothing is published on `cmd/`.

Times: ISO 8601; without an offset, local time of the greenhouse. Answers are in local time.
"""

import json
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from common.mqtt import PHYSICAL_RANGE, Actuator, Ordre, SensorType, sensor_topic
from common.mqtt.schemas import Decision, PreuveCapteur, Preuves, PreuveVision, SanteEtat
from edge.controller.config import ROOT, ReglesCfg
from edge.controller.recipes import StageSetpoints

from ..consumption import energy_kwh, water_l
from ..consumption import summary as consumption_summary
from ..db import models as m
from ..db.session import utc
from ..traceability import (
    build_tree,
    decision_record,
    decision_summary,
    publish_decision,
    reconcile,
    stored_row,
    sync_actions,
)
from .config import AgentConfig
from .consignes import label as consigne_label

CATALOGUE = Path(__file__).with_name("regles.yaml")
REGLES_YAML = ROOT / "edge/controller/regles.yaml"
MAX_DECISIONS = 30
MAX_VISION = 60
AGREGATS = {"brut": None, "moy_15min": timedelta(minutes=15), "moy_1h": timedelta(hours=1)}
# Recipe values the agent may change: ranges [min, max] or single values.
RANGES = ("temperature.jour", "temperature.nuit", "humidite", "ph", "ec", "humidite_sol")
SCALARS = ("co2_max", "dli_cible", "photoperiode_h")


class ToolError(Exception):
    """Refusal returned to the LLM as a tool error (`is_error`), nothing created."""


def load_catalogue() -> dict[str, dict]:
    return yaml.safe_load(CATALOGUE.read_text())


# --- arguments ---------------------------------------------------------------------------


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


Zone = Annotated[str, Field(pattern=r"^z\d+$", description="zone, ex. z1")]
Instant = Annotated[str, Field(description="ISO 8601 ; sans décalage : heure locale de la serre")]
Refs = Annotated[
    list[str],
    Field(
        min_length=1,
        description="références qui justifient la proposition, telles que renvoyées par les "
        "outils de lecture : id de décision (dec-…), image_id d'un résultat vision, série "
        "de mesures (champ `ref` de get_mesures : mesure:<zone>/<type>/<debut>/<fin>)",
    ),
]
Justification = Annotated[str, Field(min_length=1, description="pourquoi, en une ou deux phrases")]


class NoArgs(_Args):
    pass


class PlanteArgs(_Args):
    emplacement: str | None = Field(None, description="emplacement, ex. z1-A1")
    plante_id: str | None = Field(None, description="id de plante, ex. tomate-1")

    @model_validator(mode="after")
    def _one(self) -> "PlanteArgs":
        if (self.emplacement is None) == (self.plante_id is None):
            raise ValueError("donner emplacement ou plante_id (un seul)")
        return self


class MesuresArgs(_Args):
    zone: Zone
    types: list[SensorType] = Field(min_length=1, description="types de mesure")
    debut: Instant | None = Field(None, description="défaut : fin − 24 h")
    fin: Instant | None = Field(None, description="défaut : maintenant")
    agregat: Literal["brut", "moy_15min", "moy_1h"] = "moy_15min"
    emplacement: str | None = Field(None, description="sondes de sol : un emplacement")


class VisionArgs(_Args):
    emplacement: str = Field(description="emplacement, ex. z1-A1")
    debut: Instant | None = Field(None, description="défaut : fin − 72 h")
    fin: Instant | None = None


class DecisionsArgs(_Args):
    decision_id: str | None = Field(None, description="une décision précise (fiche complète)")
    zone: Zone | None = None
    debut: Instant | None = Field(None, description="défaut : fin − 24 h")
    fin: Instant | None = None
    type: Literal["routine", "exceptionnelle", "securite", "manuelle"] | None = None
    statut: str | None = Field(None, description="proposee, executee, terminee, expiree…")
    regle: str | None = Field(None, description="id de règle, ex. maladie.mildiou.ventilation")


class ArbreArgs(_Args):
    zone: Zone | None = None
    debut: Instant | None = Field(None, description="défaut : fin − 24 h")
    fin: Instant | None = None


class ConsommationArgs(_Args):
    zone: Zone | None = None
    periode: Literal["jour", "semaine", "mois"] = "jour"
    jour: date | None = Field(None, description="dernier jour de la période, défaut : aujourd'hui")


class RegleArgs(_Args):
    regle_id: str


class ActionArgs(_Args):
    zone: Zone
    actionneur: Actuator
    action: Literal["on", "off", "pwm"]
    valeur: float | None = Field(None, ge=0, le=100, description="% pour pwm, seulement")
    duree_s: float | None = Field(None, gt=0, description="obligatoire sauf pour off")
    justification: Justification
    preuves_refs: Refs


class ConsigneArgs(_Args):
    recette_id: str
    stade: str
    grandeur: Literal[RANGES + SCALARS]  # type: ignore[valid-type]
    plage: list[float] = Field(
        min_length=1, max_length=2, description="[min, max] pour une plage, [valeur] sinon"
    )
    duree_h: float | None = Field(None, gt=0, description="temporaire ; absent : permanent")
    zone: Zone | None = Field(None, description="défaut : la zone des plantes de cette recette")
    justification: Justification
    preuves_refs: Refs


class EtatPlanteArgs(_Args):
    plante_id: str
    etat_sante: SanteEtat
    justification: Justification
    preuves_refs: Refs


class CaptureArgs(_Args):
    camera: str
    justification: Justification


def _schema(model: type[BaseModel]) -> dict:
    """JSON schema of the arguments, without the pydantic titles."""

    def clean(node):
        if isinstance(node, dict):
            return {k: clean(v) for k, v in node.items() if k != "title"}
        if isinstance(node, list):
            return [clean(v) for v in node]
        return node

    return clean(model.model_json_schema())


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args: type[_Args]
    proposition: bool = False

    def definition(self) -> dict:
        return dict(name=self.name, description=self.description, input_schema=_schema(self.args))


SPECS = [
    ToolSpec("get_serre", "Zones, emplacements, plantes actives, équipements et limites de "
             "sécurité de la serre.", NoArgs),
    ToolSpec("get_plante", "Fiche d'une plante (par emplacement ou id) : espèce, stade, recette "
             "du stade, état de santé et son historique, dernières classifications.", PlanteArgs),
    ToolSpec("get_mesures", "Séries de mesures d'une zone (≤ 500 points par type), avec min, max, "
             "moyenne et une référence `ref` citable dans les propositions.", MesuresArgs),
    ToolSpec("get_vision", "Résultats vision d'un emplacement (classe, confiances, anomalie, "
             "surface verte, image_id), du plus récent au plus ancien.", VisionArgs),
    ToolSpec("get_decisions", "Journal des décisions avec leurs preuves (vision, capteurs, "
             "prévision, consignes), ordres et actions ; ou la fiche d'une décision.",
             DecisionsArgs),
    ToolSpec("get_arbre_actions", "Arbre des actions : zones → routines agrégées / "
             "exceptionnelles / sécurité / manuelles → décisions → actions et résultats.",
             ArbreArgs),
    ToolSpec("get_consommation", "Consommation estimée par actionneur (kWh, litres, mL "
             "d'intrants, coût) et lumière du jour (DLI mesuré, part LED) sur la période.",
             ConsommationArgs),
    ToolSpec("get_regle", "Description d'une règle du contrôleur, sa version et ses seuils "
             "courants.", RegleArgs),
    ToolSpec("proposer_action", "Propose une commande d'actionneur (validation par "
             "l'utilisateur, puis safety.py). Durée obligatoire sauf off, bornée par la "
             "durée max de l'actionneur.", ActionArgs, True),
    ToolSpec("proposer_consigne", "Propose de modifier une consigne de recette pour un stade, "
             "temporairement (duree_h) ou durablement ; appliquée après validation.",
             ConsigneArgs, True),
    ToolSpec("proposer_etat_plante", "Propose un nouvel état de santé d'une plante "
             "(a_surveiller, malade, isolee…) ; appliqué après validation.", EtatPlanteArgs,
             True),
    ToolSpec("demander_capture", "Capture immédiate d'une caméra (seule action exécutée sans "
             "validation, sans effet sur les plantes).", CaptureArgs, True),
]  # fmt: skip
BY_NAME = {s.name: s for s in SPECS}


def definitions() -> list[dict]:
    """Tool definitions for the API, in a fixed order (prompt cache)."""
    return [s.definition() for s in SPECS]


# --- results -----------------------------------------------------------------------------


@dataclass
class ToolResult:
    content: dict
    error: bool = False
    proposition: dict | None = None  # record of the created decision (UI card)
    resume: str = ""

    def text(self) -> str:
        return json.dumps(self.content, ensure_ascii=False, separators=(",", ":"), default=str)


@dataclass
class Tools:
    """`publisher`: edge.publisher.Publisher; None: `demander_capture` refused."""

    sessions: sessionmaker[Session]
    publisher: Any = None
    cfg: AgentConfig = field(default_factory=AgentConfig)
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def run(self, name: str, args: Any, conversation_id: str | None = None) -> ToolResult:
        spec = BY_NAME.get(name)
        if spec is None:
            return ToolResult({"erreur": f"outil inconnu {name!r}"}, error=True)
        try:
            parsed = spec.args.model_validate(args if isinstance(args, dict) else {})
        except ValidationError as e:
            msgs = [
                f"{'.'.join(map(str, x['loc'])) or 'arguments'} : {x['msg']}" for x in e.errors()
            ]
            return ToolResult({"erreur": "arguments invalides", "details": msgs}, error=True)
        try:
            with self.sessions.begin() as s:
                ctx = _Ctx(s, self, utc(self.clock()), conversation_id)
                return getattr(ctx, name)(parsed)
        except ToolError as e:
            return ToolResult({"erreur": str(e)}, error=True, resume=f"refus : {e}")


@dataclass
class _Ctx:
    s: Session
    tools: Tools
    now: datetime
    conversation_id: str | None

    # --- helpers -----------------------------------------------------------------------

    @property
    def serre(self) -> m.Serre:
        serre = self.s.scalars(select(m.Serre)).first()
        if serre is None:
            raise ToolError("aucune serre en base")
        return serre

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.serre.fuseau)

    def t(self, ts: datetime | None) -> str | None:
        if ts is None:
            return None
        return utc(ts).astimezone(self.tz).isoformat(timespec="seconds")

    def parse(self, text: str | None, default: datetime) -> datetime:
        if text is None:
            return default
        try:
            ts = datetime.fromisoformat(text)
        except ValueError:
            raise ToolError(f"instant illisible {text!r} (ISO 8601 attendu)") from None
        return utc(ts if ts.tzinfo else ts.replace(tzinfo=self.tz))

    def window(self, debut: str | None, fin: str | None, hours: float) -> tuple[datetime, datetime]:
        f = self.parse(fin, self.now)
        d = self.parse(debut, f - timedelta(hours=hours))
        if d >= f:
            raise ToolError("debut doit précéder fin")
        return d, f

    def zone(self, zone: str) -> m.Zone:
        z = self.s.get(m.Zone, zone)
        if z is None:
            zones = ", ".join(self.s.scalars(select(m.Zone.id).order_by(m.Zone.id)))
            raise ToolError(f"zone inconnue {zone} (zones : {zones})")
        return z

    def current_plant(self, emplacement: str) -> m.Plante | None:
        aff = self.s.scalars(
            select(m.Affectation).where(
                m.Affectation.emplacement_id == emplacement, m.Affectation.fin.is_(None)
            )
        ).first()
        return self.s.get(m.Plante, aff.plante_id) if aff else None

    def plant_place(self, plante_id: str) -> str | None:
        return self.s.scalar(
            select(m.Affectation.emplacement_id).where(
                m.Affectation.plante_id == plante_id, m.Affectation.fin.is_(None)
            )
        )

    def securite(self) -> dict:
        return (self.serre.parametres or {}).get("securite", {})

    def _vision_row(self, r: m.VisionResultat) -> dict:
        return dict(
            ts=self.t(r.ts),
            image_id=r.image_id,
            camera=r.camera,
            emplacement=r.emplacement_id,
            modele=r.modele,
            classe=r.classe,
            classe_conf=round(r.classe_conf, 3),
            sante=r.sante,
            sante_conf=round(r.sante_conf, 3),
            espece=r.espece,
            espece_conf=round(r.espece_conf, 3),
            score_anomalie=round(r.score_anomalie, 3),
            surface_verte_px=r.surface_verte_px,
            bbox=r.bbox,
            image=f"/images/{r.image_id}",
            gradcam=f"/images/{r.image_id}?gradcam=1",
        )

    def _decision(self, d: m.Decision, full: bool) -> dict:
        out = decision_record(self.s, d) if full else decision_summary(d)
        out["ts"] = self.t(d.ts)
        out["expire"] = self.t(d.expire)
        if full:
            for a in out["actions_detail"]:
                a["ts_debut"], a["ts_fin"] = self.t(a["ts_debut"]), self.t(a["ts_fin"])
            for c in out["commandes"]:
                c["ts"] = self.t(c["ts"])
        return out

    # --- reading -----------------------------------------------------------------------

    def get_serre(self, _: NoArgs) -> ToolResult:
        return ToolResult(serre_summary(self.s), resume="serre")

    def get_plante(self, a: PlanteArgs) -> ToolResult:
        if a.plante_id is not None:
            p = self.s.get(m.Plante, a.plante_id)
            if p is None:
                raise ToolError(f"plante inconnue {a.plante_id}")
            emp = self.plant_place(p.id)
        else:
            if self.s.get(m.Emplacement, a.emplacement) is None:
                raise ToolError(f"emplacement inconnu {a.emplacement}")
            emp, p = a.emplacement, self.current_plant(a.emplacement)
            if p is None:
                return ToolResult({"emplacement": emp, "plante": None}, resume=f"{emp} vide")
        recette = self.s.get(m.Recette, p.recette_id) if p.recette_id else None
        historique = []
        if emp is not None:
            for act in self.s.scalars(
                select(m.Action)
                .where(m.Action.cible == f"plante:{emp}")
                .order_by(m.Action.ts_debut)
            ):
                historique.append(
                    dict(ts=self.t(act.ts_debut), etat=act.label.split()[-1],
                         resultat=act.resultat, decision_id=act.decision_id)
                )  # fmt: skip
        vision = []
        if emp is not None:
            rows = self.s.scalars(
                select(m.VisionResultat)
                .where(m.VisionResultat.emplacement_id == emp)
                .order_by(m.VisionResultat.ts.desc())
                .limit(5)
            )
            vision = [self._vision_row(r) for r in rows]
        out = dict(
            plante=dict(
                id=p.id,
                espece=p.espece,
                variete=p.variete,
                stade=p.stade,
                recette=p.recette_id,
                etat_sante=p.etat_sante,
                prioritaire=p.prioritaire,
                date_semis=p.date_semis,
                date_plantation=p.date_plantation,
                notes=p.notes,
            ),
            emplacement=emp,
            zone=emp.split("-")[0] if emp else None,
            consignes_stade=(recette.stades.get(p.stade) if recette else None),
            historique_sante=historique,
            dernieres_classifications=vision,
        )
        return ToolResult(out, resume=f"plante {p.id}")

    def get_mesures(self, a: MesuresArgs) -> ToolResult:
        self.zone(a.zone)
        debut, fin = self.window(a.debut, a.fin, 24)
        step = AGREGATS[a.agregat]
        series = []
        for typ in a.types:
            q = select(m.Mesure.ts, m.Mesure.valeur, m.Mesure.unite).where(
                m.Mesure.zone == a.zone,
                m.Mesure.type == typ.value,
                m.Mesure.qualite != "erreur",
                m.Mesure.ts >= debut,
                m.Mesure.ts < fin,
            )
            if a.emplacement:
                q = q.where(m.Mesure.emplacement == a.emplacement)
            rows = [(utc(t), v, u) for t, v, u in self.s.execute(q.order_by(m.Mesure.ts))]
            values = [v for _, v, _ in rows]
            pts = _resample(
                [(t, v) for t, v, _ in rows], debut, fin, step, self.tools.cfg.max_points
            )
            series.append(
                dict(
                    type=typ.value,
                    unite=rows[0][2] if rows else PHYSICAL_RANGE[typ].unite,
                    n_mesures=len(rows),
                    min=min(values) if values else None,
                    max=max(values) if values else None,
                    moyenne=round(sum(values) / len(values), 3) if values else None,
                    ref=f"mesure:{a.zone}/{typ.value}/{self.t(debut)}/{self.t(fin)}",
                    points=[[self.t(t), round(v, 3)] for t, v in pts],
                )
            )
        out = dict(zone=a.zone, debut=self.t(debut), fin=self.t(fin), agregat=a.agregat,
                   series=series)  # fmt: skip
        return ToolResult(out, resume=f"mesures {a.zone} {', '.join(t.value for t in a.types)}")

    def get_vision(self, a: VisionArgs) -> ToolResult:
        if self.s.get(m.Emplacement, a.emplacement) is None:
            raise ToolError(f"emplacement inconnu {a.emplacement}")
        debut, fin = self.window(a.debut, a.fin, 72)
        rows = list(
            self.s.scalars(
                select(m.VisionResultat)
                .where(
                    m.VisionResultat.emplacement_id == a.emplacement,
                    m.VisionResultat.ts >= debut,
                    m.VisionResultat.ts < fin,
                )
                .order_by(m.VisionResultat.ts.desc())
                .limit(MAX_VISION)
            )
        )
        out = dict(emplacement=a.emplacement, debut=self.t(debut), fin=self.t(fin),
                   resultats=[self._vision_row(r) for r in rows])  # fmt: skip
        return ToolResult(out, resume=f"vision {a.emplacement} ({len(rows)})")

    def get_decisions(self, a: DecisionsArgs) -> ToolResult:
        reconcile(self.s, self.now)
        if a.decision_id:
            d = self.s.get(m.Decision, a.decision_id)
            if d is None:
                raise ToolError(f"décision inconnue {a.decision_id}")
            return ToolResult(self._decision(d, True), resume=f"décision {d.id}")
        debut, fin = self.window(a.debut, a.fin, 24)
        q = select(m.Decision).where(m.Decision.ts >= debut, m.Decision.ts < fin)
        filters = {"zone": a.zone, "type": a.type, "statut": a.statut, "regle_id": a.regle}
        for col, value in filters.items():
            if value:
                q = q.where(getattr(m.Decision, col) == value)
        total = self.s.scalar(select(func.count()).select_from(q.subquery()))
        rows = self.s.scalars(q.order_by(m.Decision.ts.desc()).limit(MAX_DECISIONS))
        out = dict(debut=self.t(debut), fin=self.t(fin), total=total,
                   decisions=[self._decision(d, True) for d in rows])  # fmt: skip
        if total > MAX_DECISIONS:
            out["note"] = f"{MAX_DECISIONS} plus récentes sur {total} : resserrer la période"
        where = a.zone or "toutes zones"
        return ToolResult(
            out, resume=f"décisions {where} {self.t(debut)[11:16]}–{self.t(fin)[11:16]}"
        )

    def get_arbre_actions(self, a: ArbreArgs) -> ToolResult:
        reconcile(self.s, self.now)
        debut, fin = self.window(a.debut, a.fin, 24)
        return ToolResult(build_tree(self.s, debut, fin, a.zone), resume="arbre des actions")

    def get_consommation(self, a: ConsommationArgs) -> ToolResult:
        out = consumption_summary(self.s, a.periode, a.zone, a.jour, self.now)
        out.pop("par_jour")  # the totals are enough for the agent
        return ToolResult(out, resume=f"consommation {a.periode}")

    def get_regle(self, a: RegleArgs) -> ToolResult:
        catalogue = load_catalogue()
        entry = catalogue.get(a.regle_id)
        if entry is None:
            close = [k for k in catalogue if k.split(".")[0] == a.regle_id.split(".")[0]]
            raise ToolError(f"règle inconnue {a.regle_id} (voisines : {', '.join(close) or '—'})")
        params = {}
        serre_params = self.serre.parametres or {}
        regles = load_regles()
        for key in entry.get("parametres", []):
            section, _, name = key.partition(".")
            if section == "regles":
                params[key] = getattr(regles, name, None)
            else:
                params[key] = (serre_params.get(section) or {}).get(name)
        week = self.now - timedelta(days=7)
        q = select(m.Decision).where(m.Decision.regle_id == a.regle_id, m.Decision.ts >= week)
        recent = list(self.s.scalars(q.order_by(m.Decision.ts.desc())))
        out = dict(
            id=a.regle_id,
            **entry,
            valeurs=params,
            validation_requise=regles.validation.get(a.regle_id),
            decisions_7j=len(recent),
            derniere_decision=recent[0].id if recent else None,
        )
        return ToolResult(out, resume=f"règle {a.regle_id}")

    # --- proposals ---------------------------------------------------------------------

    def proposer_action(self, a: ActionArgs) -> ToolResult:
        self.zone(a.zone)
        act = self.s.scalars(
            select(m.Actionneur).where(
                m.Actionneur.zone_id == a.zone, m.Actionneur.type == a.actionneur.value
            )
        ).first()
        if act is None:
            q = select(m.Actionneur.type).where(m.Actionneur.zone_id == a.zone)
            have = ", ".join(self.s.scalars(q.order_by(m.Actionneur.type)))
            raise ToolError(
                f"securite.actionneur_inconnu : pas de {a.actionneur} dans {a.zone} "
                f"(actionneurs : {have})"
            )
        if a.action == "pwm" and act.commande != "pwm":
            raise ToolError(f"{act.id} se commande en on/off, pas en pwm")
        if a.action != "off":
            if a.duree_s is None:
                raise ToolError("duree_s obligatoire : une proposition est toujours bornée")
            limit = act.duree_max_s or self.tools.cfg.duree_max_defaut_s
            if a.duree_s > limit:
                raise ToolError(
                    f"securite.duree_max : {a.duree_s:g} s > {limit:g} s autorisées pour {act.id}"
                )
        try:
            ordre = Ordre(cible=f"actionneur:{a.actionneur}", action=a.action, valeur=a.valeur,
                          duree_s=a.duree_s if a.action != "off" else None,
                          texte=a.justification[:120])  # fmt: skip
        except ValueError as e:
            raise ToolError(str(e).splitlines()[-1]) from None
        preuves, emps = self.evidence(a.preuves_refs)
        d = self.create(
            zone=a.zone,
            regle="agent.action",
            explication=self.explain(a.justification, ordre.label(), a.preuves_refs),
            ordres=[ordre],
            labels=[f"proposee:{ordre.label()}"],
            preuves=preuves,
            emplacements=emps,
            outil="proposer_action",
            justification=a.justification,
            refs=a.preuves_refs,
        )
        record = self._decision(d, True)
        record["estimation"] = _estimate(act, ordre)
        return ToolResult(
            dict(proposition=record, note="en attente de validation par l'utilisateur"),
            proposition=record,
            resume=f"proposition {d.id} : {ordre.label()}",
        )

    def proposer_consigne(self, a: ConsigneArgs) -> ToolResult:
        r = self.s.get(m.Recette, a.recette_id)
        if r is None:
            raise ToolError(f"recette inconnue {a.recette_id}")
        if a.stade not in r.stades:
            raise ToolError(f"stade {a.stade} absent de {a.recette_id} ({', '.join(r.stades)})")
        if a.grandeur in RANGES:
            if len(a.plage) != 2 or a.plage[0] > a.plage[1]:
                raise ToolError(f"{a.grandeur} : plage [min, max] attendue")
            valeur: Any = [float(a.plage[0]), float(a.plage[1])]
        else:
            if len(a.plage) != 1:
                raise ToolError(f"{a.grandeur} : une seule valeur attendue")
            valeur = float(a.plage[0])
        self.check_limits(a.grandeur, valeur)
        from .consignes import with_value

        try:
            StageSetpoints.model_validate(
                with_value(r.stades, a.stade, a.grandeur, valeur)[a.stade]
            )
        except ValidationError as e:
            raise ToolError(f"consigne invalide : {e.errors()[0]['msg']}") from None
        zone = a.zone or self.recipe_zone(a.recette_id, a.stade)
        self.zone(zone)
        consigne = dict(recette_id=a.recette_id, stade=a.stade, grandeur=a.grandeur,
                        valeur=valeur, duree_h=a.duree_h)  # fmt: skip
        text = consigne_label(consigne)
        preuves, emps = self.evidence(a.preuves_refs)
        d = self.create(
            zone=zone,
            regle="agent.consigne",
            explication=self.explain(a.justification, text, a.preuves_refs),
            ordres=[],
            labels=[f"proposee:{text}"],
            preuves=preuves,
            emplacements=emps,
            outil="proposer_consigne",
            justification=a.justification,
            refs=a.preuves_refs,
            consigne=consigne,
        )
        record = self._decision(d, True)
        record["consigne"] = dict(consigne, actuelle=_get(r.stades, a.stade, a.grandeur))
        return ToolResult(
            dict(proposition=record, note="appliquée à la recette après validation"),
            proposition=record,
            resume=f"proposition {d.id} : {text}",
        )

    def proposer_etat_plante(self, a: EtatPlanteArgs) -> ToolResult:
        p = self.s.get(m.Plante, a.plante_id)
        if p is None:
            raise ToolError(f"plante inconnue {a.plante_id}")
        emp = self.plant_place(p.id)
        if emp is None:
            raise ToolError(f"{p.id} n'occupe aucun emplacement")
        if p.etat_sante == a.etat_sante:
            raise ToolError(f"{p.id} est déjà « {p.etat_sante} »")
        ordre = Ordre(cible=f"plante:{emp}", action=a.etat_sante, texte=a.justification[:120])
        preuves, _ = self.evidence(a.preuves_refs, emp)
        d = self.create(
            zone=emp.split("-")[0],
            regle="agent.plante",
            explication=self.explain(a.justification, ordre.label(), a.preuves_refs),
            ordres=[ordre],
            labels=[f"proposee:{ordre.label()}"],
            preuves=preuves,
            emplacements=[emp],
            outil="proposer_etat_plante",
            justification=a.justification,
            refs=a.preuves_refs,
        )
        record = self._decision(d, True)
        record["etat_actuel"] = p.etat_sante
        return ToolResult(
            dict(proposition=record, note="en attente de validation par l'utilisateur"),
            proposition=record,
            resume=f"proposition {d.id} : {ordre.label()}",
        )

    def demander_capture(self, a: CaptureArgs) -> ToolResult:
        cam = self.s.get(m.Camera, a.camera)
        if cam is None:
            cams = ", ".join(self.s.scalars(select(m.Camera.id).order_by(m.Camera.id)))
            raise ToolError(f"caméra inconnue {a.camera} (caméras : {cams})")
        pub = self.tools.publisher
        if pub is None:
            raise ToolError("pas de connexion MQTT : capture impossible")
        ordre = Ordre(cible=f"camera:{cam.id}", action="capture", texte=a.justification[:120])
        d = self.create(
            zone=cam.zone_id,
            regle="agent.capture",
            explication=f"{a.justification} → {ordre.label()} (demande de l'agent)",
            ordres=[ordre],
            labels=[f"proposee:{ordre.label()}"],
            preuves=Preuves(),
            emplacements=[],
            outil="demander_capture",
            justification=a.justification,
            refs=[],
            statut="validee",
        )
        record = self._decision(d, False)
        return ToolResult(
            dict(decision=record, note="capture demandée au contrôleur ; le résultat vision "
                 "arrive en général en moins d'une minute (get_vision)"),
            resume=f"capture {cam.id} ({d.id})",
        )  # fmt: skip

    # --- proposal helpers --------------------------------------------------------------

    def check_limits(self, grandeur: str, valeur) -> None:
        """Safety limits of the greenhouse (serre.yaml `securite`) and physical ranges."""
        lim = self.securite()
        values = valeur if isinstance(valeur, list) else [valeur]
        if grandeur.startswith("temperature"):
            lo, hi, src = lim.get("t_min", 5), lim.get("t_max", 35), "securite.t_min/t_max"
        elif grandeur == "ph":
            lo, hi, src = lim.get("ph_min", 4.5), lim.get("ph_max", 8.0), "securite.ph_min/ph_max"
        elif grandeur in ("humidite", "humidite_sol"):
            lo, hi, src = 0, 100, "plage physique"
        elif grandeur == "ec":
            lo, hi, src = (
                PHYSICAL_RANGE[SensorType.EC].min,
                PHYSICAL_RANGE[SensorType.EC].max,
                "plage physique",
            )
        elif grandeur == "co2_max":
            lo, hi, src = (
                PHYSICAL_RANGE[SensorType.CO2].min,
                PHYSICAL_RANGE[SensorType.CO2].max,
                "plage physique",
            )
        elif grandeur == "photoperiode_h":
            lo, hi, src = 0, 24, "plage physique"
        else:  # dli_cible
            lo, hi, src = 0, 65, "plage physique"
        bad = [v for v in values if not lo <= v <= hi]
        if bad:
            raise ToolError(
                f"hors limites de sécurité : {grandeur} {bad[0]:g} hors de [{lo:g}, {hi:g}] ({src})"
            )

    def recipe_zone(self, recette_id: str, stade: str) -> str:
        zones = set()
        for p in self.s.scalars(
            select(m.Plante).where(m.Plante.recette_id == recette_id, m.Plante.stade == stade)
        ):
            emp = self.plant_place(p.id)
            if emp:
                zones.add(emp.split("-")[0])
        if len(zones) != 1:
            found = ", ".join(sorted(zones)) or "aucune"
            raise ToolError(f"zone à préciser : plantes {recette_id}/{stade} dans {found}")
        return zones.pop()

    def evidence(
        self, refs: list[str], emplacement: str | None = None
    ) -> tuple[Preuves, list[str]]:
        """Evidence of the references; an unknown reference is refused (no invented proof).
        `emplacement`: of an image, only the detections of this emplacement (if any)."""
        vision, capteurs, emps, unknown = [], [], set(), []
        for ref in dict.fromkeys(refs):
            if ref.startswith("dec-"):
                if self.s.get(m.Decision, ref) is None:
                    unknown.append(ref)
            elif ref.startswith("mesure:"):
                p = self._measure_ref(ref)
                if p is None:
                    unknown.append(ref)
                else:
                    capteurs.append(p)
            else:
                rows = list(self.s.scalars(
                    select(m.VisionResultat).where(m.VisionResultat.image_id == ref)
                    .order_by(m.VisionResultat.idx)
                ))  # fmt: skip
                if not rows:
                    unknown.append(ref)
                mine = [r for r in rows if r.emplacement_id == emplacement]
                rows = mine or rows
                for r in rows:
                    vision.append(
                        PreuveVision(camera=r.camera, image_id=r.image_id, modele=r.modele,
                                     classe=r.classe, classe_conf=r.classe_conf, sante=r.sante,
                                     sante_conf=r.sante_conf, espece=r.espece,
                                     espece_conf=r.espece_conf,
                                     bbox=tuple(r.bbox) if r.bbox else None,
                                     score_anomalie=r.score_anomalie, emplacement=r.emplacement_id)
                    )  # fmt: skip
                    if r.emplacement_id:
                        emps.add(r.emplacement_id)
        if unknown:
            raise ToolError(
                f"références introuvables : {', '.join(unknown)} (citer des id renvoyés par "
                "les outils de lecture : dec-…, image_id, ref de get_mesures)"
            )
        return Preuves(vision=vision, capteurs=capteurs), sorted(emps)

    def _measure_ref(self, ref: str) -> PreuveCapteur | None:
        try:
            zone, typ, rest = ref.removeprefix("mesure:").split("/", 2)
            debut_s, fin_s = _split_interval(rest)
            sensor = SensorType(typ)
            debut, fin = self.parse(debut_s, self.now), self.parse(fin_s, self.now)
        except (ValueError, ToolError):
            return None
        row = self.s.execute(
            select(func.avg(m.Mesure.valeur), func.count(), func.min(m.Mesure.unite)).where(
                m.Mesure.zone == zone,
                m.Mesure.type == sensor.value,
                m.Mesure.qualite != "erreur",
                m.Mesure.ts >= debut,
                m.Mesure.ts < fin,
            )
        ).one()
        if not row[1]:
            return None
        hours = (fin - debut).total_seconds() / 3600
        return PreuveCapteur(topic=sensor_topic(zone, sensor), agregat=f"moyenne_{hours:g}h",
                             valeur=round(row[0], 3), unite=row[2])  # fmt: skip

    def explain(self, justification: str, what: str, refs: list[str]) -> str:
        return f"{justification} → {what} (proposition de l'agent ; preuves : {', '.join(refs)})"

    def create(
        self,
        *,
        zone: str,
        regle: str,
        explication: str,
        ordres: list[Ordre],
        labels: list[str],
        preuves: Preuves,
        emplacements: list[str],
        outil: str,
        justification: str,
        refs: list[str],
        consigne: dict | None = None,
        statut: str = "proposee",
    ) -> m.Decision:
        now = self.now
        expire = (
            now + timedelta(seconds=self.tools.cfg.expiration_s) if statut == "proposee" else None
        )
        version = load_catalogue()[regle]["version"]
        msg = Decision(
            id=f"dec-{now:%Y%m%d-%H%M}-{zone}-ag{uuid.uuid4().hex[:6]}",
            ts=now,
            zone=zone,
            emplacements=emplacements,
            niveau="agent",
            origine="agent",
            regle={"id": regle, "version": version},
            type="manuelle",
            config_version=self.serre.config_version,
            preuves=preuves,
            explication=explication,
            actions=labels,
            ordres=ordres,
            statut=statut,
            expire=expire,
        )
        self.s.merge(m.Decision(**stored_row(msg)))
        self.s.add(
            m.AgentProposition(decision_id=msg.id, conversation_id=self.conversation_id,
                               outil=outil, justification=justification, preuves_refs=refs,
                               consigne=consigne)
        )  # fmt: skip
        self.s.flush()
        if statut == "proposee":
            sync_actions(self.s, [msg.id])  # not published before validation (docs/11 §4.1)
        else:
            publish_decision(self.tools.publisher, msg)  # the ingestion traces it
        return self.s.get(m.Decision, msg.id)


# --- module helpers ----------------------------------------------------------------------


def load_regles() -> ReglesCfg:
    if not REGLES_YAML.exists():
        return ReglesCfg()
    return ReglesCfg.model_validate(yaml.safe_load(REGLES_YAML.read_text()) or {})


def serre_summary(s: Session) -> dict:
    """Zones, emplacements, active plants, equipment and safety limits (`get_serre`, and
    the system prompt)."""
    serre = s.scalars(select(m.Serre)).first()
    if serre is None:
        raise ToolError("aucune serre en base")
    zones = []
    for z in s.scalars(select(m.Zone).order_by(m.Zone.id)):
        emps = []
        for e in s.scalars(
            select(m.Emplacement).where(m.Emplacement.zone_id == z.id).order_by(m.Emplacement.id)
        ):
            aff = s.scalars(
                select(m.Affectation).where(
                    m.Affectation.emplacement_id == e.id, m.Affectation.fin.is_(None)
                )
            ).first()
            p = s.get(m.Plante, aff.plante_id) if aff else None
            emps.append(
                dict(
                    id=e.id,
                    mode_culture=e.mode_culture,
                    plante=dict(id=p.id, espece=p.espece, variete=p.variete, stade=p.stade,
                                recette=p.recette_id, etat_sante=p.etat_sante,
                                prioritaire=p.prioritaire) if p else None,
                )
            )  # fmt: skip
        acts = [
            dict(type=a.type, id=a.id, commande=a.commande, duree_max_s=a.duree_max_s,
                 puissance_w=a.puissance_w)
            for a in s.scalars(
                select(m.Actionneur).where(m.Actionneur.zone_id == z.id).order_by(m.Actionneur.type)
            )
        ]  # fmt: skip
        cams = []
        for c in s.scalars(select(m.Camera).where(m.Camera.zone_id == z.id).order_by(m.Camera.id)):
            vis = s.scalars(
                select(m.CameraRegion.emplacement_id)
                .where(m.CameraRegion.camera_id == c.id)
                .order_by(m.CameraRegion.emplacement_id)
            )
            cams.append(dict(id=c.id, emplacements=list(vis)))
        types = sorted(set(s.scalars(select(m.Capteur.type).where(m.Capteur.zone == z.id))))
        zones.append(dict(id=z.id, nom=z.nom, cuve=z.cuve_id, jour_debut=z.jour_debut,
                          presence_autorisee=z.presence_autorisee, emplacements=emps,
                          actionneurs=acts, cameras=cams, mesures=types))  # fmt: skip
    return dict(
        serre=serre.nom,
        fuseau=serre.fuseau,
        config_version=serre.config_version,
        tarif_kwh=serre.tarif_kwh,
        securite=(serre.parametres or {}).get("securite", {}),
        zones=zones,
    )


def _r(v: float | None, n: int = 3) -> float | None:
    return round(v, n) if v is not None else None


def _get(stades: dict, stade: str, grandeur: str):
    from .consignes import get_value

    return get_value(stades, stade, grandeur)


def _split_interval(rest: str) -> tuple[str, str]:
    """ "<debut>/<fin>" where both are ISO instants (no "/" inside)."""
    debut, sep, fin = rest.partition("/")
    if not sep:
        raise ValueError(rest)
    return debut, fin


def _resample(
    pts: list[tuple[datetime, float]],
    debut: datetime,
    fin: datetime,
    step: timedelta | None,
    max_points: int,
) -> list[tuple[datetime, float]]:
    """Means over buckets of `step` (None: raw), widened so that at most `max_points`
    remain; each bucket is stamped with its start."""
    span = (fin - debut).total_seconds()
    if step is None and len(pts) <= max_points:
        return pts
    width = max(step.total_seconds() if step else 0.0, span / max_points)
    buckets: dict[int, list[float]] = defaultdict(list)
    for t, v in pts:
        buckets[int((t - debut).total_seconds() // width)].append(v)
    return [
        (debut + timedelta(seconds=i * width), sum(vs) / len(vs))
        for i, vs in sorted(buckets.items())
    ]


def _estimate(act: m.Actionneur, o: Ordre) -> dict:
    """Consumption of the proposed order (UI card), like backend/consumption.py."""
    if o.action == "off" or not o.duree_s:
        return {}
    factor = (o.valeur or 0) / 100 if o.action == "pwm" else 1.0
    out = {}
    if act.puissance_w:
        out["kwh"] = round(energy_kwh(act.puissance_w, o.duree_s * factor), 3)
    kind = Actuator(act.type)
    if kind.is_pump and not kind.is_dosing and act.debit_l_h:
        out["litres"] = round(water_l(act.debit_l_h, o.duree_s), 2)
    return out


__all__ = ["SPECS", "ToolError", "ToolResult", "Tools", "definitions", "serre_summary"]
