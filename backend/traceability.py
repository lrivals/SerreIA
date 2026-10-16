"""Traceability of the decisions (docs/10): actions, their confirmation, the action tree.

    python -m backend.traceability [--zone z1] [--debut ISO] [--fin ISO] [--db URL] [--json]

- `sync_actions`: the `action` rows of a decision, derived from its labels
  (`Decision.actions`) and from the commands pointing to it (`commande.decision_id`); a
  command whose decision was lost still gives an action (docs/10 §3).
- `reconcile`: an actuator action is `confirmee` when `etat/` reflects its command within
  10 s, `non_confirmee` otherwise; a capture is confirmed by a vision result of the camera
  within 5 min; a plant action sets `plante.etat_sante`. `ts_fin` = deadline of `duree_s`,
  or the next command of the actuator. A decision `executee` whose actions are all over
  becomes `terminee`; a `proposee` one past its `expire` becomes `expiree` (docs/10 §4),
  and the actions of an expired or rejected proposal `annulee`.
- `build_tree` / `render_text`: the tree of docs/10 §6 over a period — greenhouse → zones →
  routines (aggregated per rule: cycles, time on) / exceptional / safety / manual
  decisions → their actions.

The ingestion calls `sync_actions` and `reconcile` after each written batch.
"""

import argparse
import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from common.mqtt import decision_topic
from common.mqtt.schemas import Decision as DecisionMsg

from .db import models as m
from .db.session import utc

CONFIRM_S = 10.0  # etat/ must reflect the command within this delay
CAPTURE_CONFIRM_S = 300.0
LOOKBACK = timedelta(hours=48)  # actions and decisions still followed by `reconcile`
GROUPS = ("routine", "exceptionnelle", "securite", "manuelle")
GROUP_LABELS = {
    "routine": "Routines",
    "exceptionnelle": "Exceptionnelles",
    "securite": "Sécurité",
    "manuelle": "Manuelles",
}
DONE = ("confirmee", "non_confirmee", "bloquee", "echec", "annulee")


# --- actions -----------------------------------------------------------------------------


def action_id(decision_id: str, i: int) -> str:
    return f"act-{decision_id.removeprefix('dec-')}-{i:02d}"


def parse_label(label: str) -> tuple[str, str, str]:
    """(cible, label, initial resultat) of one label of `Decision.actions`."""
    kind, sep, rest = label.partition(":")
    if not sep:
        return ("alerte" if kind == "alerte" else "autre", kind, "confirmee")
    if kind == "proposee":
        cible, text, _ = parse_label(_ordre_label(rest))
        return cible, text, "proposee"
    if kind == "cmd":
        return f"actionneur:{rest.split()[0]}", rest, "en_attente"
    if kind == "bloquee":
        return f"actionneur:{rest.split()[0]}", rest, "bloquee"
    if kind == "capture":
        return f"camera:{rest}", f"capture {rest}", "en_attente"
    if kind == "plante":
        return f"plante:{rest.split()[0]}", f"plante {rest}", "en_attente"
    if kind == "consigne":
        return "consigne", f"consigne {rest}", "confirmee"
    return "autre", label, "confirmee"


def _ordre_label(text: str) -> str:
    """`Ordre.label()` ("capture cam", "plante z1-A1 isolee", "ventilo on 900 s") → label."""
    head, _, tail = text.partition(" ")
    if head in ("capture", "plante"):
        return f"{head}:{tail}"
    return f"cmd:{text}"


def _command_json(c: m.Commande) -> dict:
    return dict(
        ts=utc(c.ts).isoformat(),
        action=c.action,
        valeur=c.valeur,
        duree_s=c.duree_s,
        source=c.source,
        raison=c.raison,
    )


def _command_label(c: m.Commande) -> str:
    s = f"{c.actionneur} {c.action}"
    if c.valeur is not None:
        s += f" {c.valeur:g} %"
    if c.duree_s is not None:
        s += f" {c.duree_s:g} s"
    return s


def _orphan_type(source: str) -> str:
    if source == "safety":
        return "securite"
    return "manuelle" if source.startswith(("ui", "agent")) else "routine"


def _stage(resultat: str) -> str:
    """proposed, blocked or run: an action changing stage starts again from its label."""
    if resultat in ("proposee", "annulee"):
        return "proposee"
    return "bloquee" if resultat == "bloquee" else "run"


def sync_actions(s: Session, decision_ids: Iterable[str]) -> None:
    """(Re)build the actions of these decisions. An action whose label and stage did not
    change keeps its result; the others start again from the label."""
    for did in set(decision_ids):
        d = s.get(m.Decision, did)
        q = select(m.Commande).where(m.Commande.decision_id == did).order_by(m.Commande.ts)
        cmds = list(s.scalars(q))
        existing = {a.id: a for a in s.scalars(select(m.Action).where(m.Action.decision_id == did))}
        if d is not None:
            zone, type_, ts = d.zone, d.type, utc(d.ts)
            specs = [parse_label(label) for label in d.actions]
        elif cmds:  # the decision was lost: the commands alone (docs/10 §3)
            zone, type_, ts = cmds[0].zone, _orphan_type(cmds[0].source), utc(cmds[0].ts)
            specs = [(f"actionneur:{c.actionneur}", _command_label(c), "en_attente") for c in cmds]
        else:
            continue
        unused = list(cmds)
        for i, (cible, label, resultat) in enumerate(specs, 1):
            cmd = None
            if cible.startswith("actionneur:") and resultat == "en_attente":
                actuator = cible.partition(":")[2]
                cmd = next((c for c in unused if c.actionneur == actuator), None)
                if cmd is not None:
                    unused.remove(cmd)
            aid = action_id(did, i)
            a = existing.pop(aid, None)
            if a is None or (a.label, a.cible, _stage(a.resultat)) != (
                label,
                cible,
                _stage(resultat),
            ):
                if a is not None:
                    s.delete(a)
                    s.flush()
                a = m.Action(id=aid, decision_id=did, cible=cible, label=label, resultat=resultat)
                a.ts_debut = utc(cmd.ts) if cmd is not None else ts
                if resultat in ("confirmee", "bloquee"):
                    a.ts_fin = a.ts_debut
                s.add(a)
            a.zone, a.type = zone, type_
            if cmd is not None and a.commande is None:
                a.commande, a.ts_debut = _command_json(cmd), utc(cmd.ts)
        for a in existing.values():
            s.delete(a)
    s.flush()


def reconcile(s: Session, now: datetime) -> None:
    now = utc(now)
    since = now - LOOKBACK
    open_ = s.scalars(
        select(m.Action).where(
            m.Action.resultat.in_(("en_attente", "non_confirmee")), m.Action.ts_debut >= since
        )
    )
    for a in open_:
        kind, _, subject = a.cible.partition(":")
        if kind == "actionneur":
            _confirm_actuator(s, a, subject, now)
        elif kind == "camera":
            _confirm_capture(s, a, subject, now)
        elif kind == "plante" and a.resultat == "en_attente":
            _apply_plant(s, a, subject, now)
    running = s.scalars(
        select(m.Action).where(
            m.Action.resultat == "confirmee", m.Action.ts_fin.is_(None), m.Action.ts_debut >= since
        )
    )
    for a in running:
        a.ts_fin = _end_of(s, a)
    s.flush()

    for d in s.scalars(
        select(m.Decision).where(m.Decision.statut == "executee", m.Decision.ts >= since)
    ):
        acts = list(s.scalars(select(m.Action).where(m.Action.decision_id == d.id)))
        over = all(
            a.resultat in DONE and (a.ts_fin is None and a.resultat != "confirmee"
                                    or a.ts_fin is not None and utc(a.ts_fin) <= now)
            for a in acts
        )  # fmt: skip
        if over:
            d.statut = "terminee"
    for d in s.scalars(
        select(m.Decision).where(m.Decision.statut == "proposee", m.Decision.expire.isnot(None))
    ):
        if utc(d.expire) <= now:
            d.statut = "expiree"
    s.flush()
    # The orders of a proposal nobody validated never run.
    closed = select(m.Decision.id).where(m.Decision.statut.in_(("expiree", "rejetee")))
    for a in s.scalars(
        select(m.Action).where(m.Action.resultat == "proposee", m.Action.decision_id.in_(closed))
    ):
        a.resultat, a.ts_fin = "annulee", now
    s.flush()


def _confirm_actuator(s: Session, a: m.Action, actuator: str, now: datetime) -> None:
    start = utc(a.ts_debut)
    late = (now - start).total_seconds() > CONFIRM_S
    if a.commande is None:
        if late:
            a.resultat = "non_confirmee"
        return
    state = s.scalars(
        select(m.EtatActionneur)
        .where(
            m.EtatActionneur.zone == a.zone,
            m.EtatActionneur.actionneur == actuator,
            m.EtatActionneur.ts <= start + timedelta(seconds=CONFIRM_S),
        )
        .order_by(m.EtatActionneur.ts.desc())
        .limit(1)
    ).first()
    want = a.commande
    if (
        state is not None
        and state.action == want["action"]
        and (want["action"] != "pwm" or state.valeur == want["valeur"])
    ):
        a.resultat = "confirmee"
    elif late:
        a.resultat = "non_confirmee"


def _confirm_capture(s: Session, a: m.Action, camera: str, now: datetime) -> None:
    start = utc(a.ts_debut)
    seen = s.scalars(
        select(m.VisionResultat.ts)
        .where(
            m.VisionResultat.camera == camera,
            m.VisionResultat.ts >= start,
            m.VisionResultat.ts <= start + timedelta(seconds=CAPTURE_CONFIRM_S),
        )
        .limit(1)
    ).first()
    if seen is not None:
        a.resultat, a.ts_fin = "confirmee", utc(seen)
    elif (now - start).total_seconds() > CAPTURE_CONFIRM_S:
        a.resultat = "non_confirmee"


def _apply_plant(s: Session, a: m.Action, emplacement: str, now: datetime) -> None:
    etat = a.label.split()[-1]
    aff = s.scalars(
        select(m.Affectation).where(
            m.Affectation.emplacement_id == emplacement, m.Affectation.fin.is_(None)
        )
    ).first()
    plante = s.get(m.Plante, aff.plante_id) if aff is not None else None
    if plante is None:
        a.resultat, a.ts_fin = "echec", now
        return
    plante.etat_sante = etat
    a.resultat, a.ts_fin = "confirmee", utc(a.ts_debut)


def _end_of(s: Session, a: m.Action) -> datetime | None:
    """End of a confirmed action: now for alerts and the like, the deadline of `duree_s`,
    or the next command of the same actuator."""
    if not a.cible.startswith("actionneur:") or a.commande is None:
        return utc(a.ts_debut)
    start = utc(a.ts_debut)
    if a.commande["action"] == "off":
        return start
    if a.commande.get("duree_s"):
        return start + timedelta(seconds=a.commande["duree_s"])
    nxt = s.scalars(
        select(m.Commande.ts)
        .where(
            m.Commande.zone == a.zone,
            m.Commande.actionneur == a.cible.partition(":")[2],
            m.Commande.ts > start,
        )
        .order_by(m.Commande.ts)
        .limit(1)
    ).first()
    return utc(nxt) if nxt is not None else None


# --- decisions (API, validation) ---------------------------------------------------------


def decision_message(d: m.Decision, **update) -> DecisionMsg:
    """The contract message of a stored decision (to publish it again with a new status)."""
    data = dict(
        id=d.id,
        ts=utc(d.ts),
        zone=d.zone,
        emplacements=d.emplacements,
        niveau=int(d.niveau) if d.niveau.isdigit() else d.niveau,
        origine=d.origine,
        regle={"id": d.regle_id, "version": d.regle_version},
        type=d.type,
        config_version=d.config_version,
        preuves=d.preuves,
        explication=d.explication,
        actions=d.actions,
        ordres=d.ordres or [],
        statut=d.statut,
        expire=utc(d.expire) if d.expire else None,
    )
    data.update(update)
    return DecisionMsg.model_validate(data)


def publish_decision(publisher, message: DecisionMsg) -> None:
    """`publisher`: edge.publisher.Publisher (MqttPublisher, LoopbackPublisher…)."""
    publisher.publish(decision_topic(message.zone), message)


def stored_row(message: DecisionMsg) -> dict:
    """Columns of the `decision` row of a contract message (ingestion, API)."""
    return dict(
        id=message.id,
        ts=utc(message.ts),
        zone=message.zone,
        emplacements=list(message.emplacements),
        niveau=str(message.niveau),
        origine=message.origine,
        regle_id=message.regle.id,
        regle_version=message.regle.version,
        type=message.type,
        config_version=message.config_version,
        preuves=message.preuves.model_dump(mode="json"),
        explication=message.explication,
        actions=list(message.actions),
        ordres=[o.model_dump(mode="json") for o in message.ordres],
        statut=message.statut,
        expire=utc(message.expire) if message.expire else None,
    )


# --- tree --------------------------------------------------------------------------------


def _iso(ts: datetime | None) -> str | None:
    return utc(ts).isoformat() if ts is not None else None


def _action_node(a: m.Action) -> dict:
    return dict(
        id=a.id,
        type="action",
        cible=a.cible,
        label=a.label,
        resultat=a.resultat,
        ts_debut=_iso(a.ts_debut),
        ts_fin=_iso(a.ts_fin),
    )


def _resume(explication: str) -> str:
    head = explication.partition(" → ")[0]
    return head if len(head) <= 90 else head[:89] + "…"


def _on_seconds(a: m.Action, debut: datetime, fin: datetime) -> float:
    if a.commande is None or a.commande["action"] == "off" or a.resultat != "confirmee":
        return 0.0
    start = max(utc(a.ts_debut), debut)
    end = min(utc(a.ts_fin) if a.ts_fin else fin, fin)
    return max(0.0, (end - start).total_seconds())


def build_tree(s: Session, debut: datetime, fin: datetime, zone: str | None = None) -> dict:
    """Tree of docs/10 §6 for the decisions of [debut, fin)."""
    debut, fin = utc(debut), utc(fin)
    q = select(m.Decision).where(m.Decision.ts >= debut, m.Decision.ts < fin)
    if zone is not None:
        q = q.where(m.Decision.zone == zone)
    decisions = list(s.scalars(q.order_by(m.Decision.ts)))
    acts: dict[str, list[m.Action]] = defaultdict(list)
    ids = [d.id for d in decisions]
    for i in range(0, len(ids), 500):
        for a in s.scalars(
            select(m.Action).where(m.Action.decision_id.in_(ids[i : i + 500])).order_by(m.Action.id)
        ):
            acts[a.decision_id].append(a)

    serre = s.scalars(select(m.Serre)).first()
    zones = {z.id: z for z in s.scalars(select(m.Zone).order_by(m.Zone.id))}
    names = sorted({d.zone for d in decisions} | ({zone} if zone else set(zones)))
    by_zone: dict[str, dict[str, list[m.Decision]]] = {z: defaultdict(list) for z in names}
    for d in decisions:
        by_zone[d.zone][d.type].append(d)

    children = []
    for z in names:
        groups = []
        for g in GROUPS:
            ds = by_zone[z].get(g, [])
            if not ds:
                continue
            if g == "routine":
                kids = _routines(z, ds, acts, debut, fin)
            else:
                kids = [_decision_node(d, acts[d.id]) for d in ds]
            groups.append(dict(id=f"{z}/{g}", type="groupe", label=GROUP_LABELS[g], children=kids))
        zcfg = zones.get(z)
        label = f"{z} ({zcfg.nom})" if zcfg is not None and zcfg.nom else z
        children.append(dict(id=z, type="zone", label=label, children=groups))
    return dict(
        id="serre",
        type="serre",
        label=f"Serre « {serre.nom if serre else 'serre'} »",
        debut=debut.isoformat(),
        fin=fin.isoformat(),
        children=children,
    )


def _decision_node(d: m.Decision, actions: list[m.Action]) -> dict:
    return dict(
        id=d.id,
        type="decision",
        ts=_iso(d.ts),
        niveau=d.niveau,
        statut=d.statut,
        regle=d.regle_id,
        resume=_resume(d.explication),
        children=[_action_node(a) for a in actions],
    )


def _routines(zone, decisions, acts, debut, fin) -> list[dict]:
    """One node per routine rule: number of cycles (decisions), actions, time on."""
    by_rule: dict[str, list[m.Decision]] = defaultdict(list)
    for d in decisions:
        by_rule[d.regle_id].append(d)
    out = []
    for rule_id, ds in sorted(by_rule.items()):
        actions = [a for d in ds for a in acts[d.id]]
        cibles = sorted({a.cible.partition(":")[2] for a in actions if a.cible.startswith("act")})
        out.append(
            dict(
                id=f"{zone}/routine/{rule_id}",
                type="routine",
                regle=rule_id,
                label=f"{rule_id} {' '.join(cibles)}".strip(),
                cycles=len(ds),
                actions=len(actions),
                confirmees=sum(a.resultat == "confirmee" for a in actions),
                echecs=sum(a.resultat in ("non_confirmee", "echec", "bloquee") for a in actions),
                duree_on_s=round(sum(_on_seconds(a, debut, fin) for a in actions)),
                derniere=_iso(ds[-1].ts),
                decisions=[d.id for d in ds],
            )
        )
    return out


SYMBOLS = {
    "confirmee": "✔",
    "en_attente": "…",
    "proposee": "⏳ proposée (attend validation)",
    "non_confirmee": "✖ non confirmée",
    "echec": "✖ échec",
    "bloquee": "✖ bloquée",
    "annulee": "– annulée (non validée)",
}


def _duration(seconds: float) -> str:
    h, rem = divmod(int(seconds), 3600)
    return f"{h} h {rem // 60:02d}" if h else f"{rem // 60} min"


def _text(node: dict) -> str:
    t = node["type"]
    if t == "routine":
        s = f"{node['label']}  ×{node['cycles']} cycle(s)"
        if node["duree_on_s"]:
            s += f" ({_duration(node['duree_on_s'])} en marche)"
        ok = "✔" if not node["echecs"] else f"✖ {node['echecs']} échec(s)"
        return f"{s}  {ok}"
    if t == "decision":
        return f"{node['id']}  {node['resume']}  [niveau {node['niveau']}, {node['statut']}]"
    if t == "action":
        return f"{node['label']}  {SYMBOLS.get(node['resultat'], node['resultat'])}"
    return node["label"]


def render_text(tree: dict) -> str:
    """ASCII view of docs/10 §6."""
    lines = [f"{tree['label']}  [{tree['debut'][:16]} → {tree['fin'][:16]}]"]

    def walk(nodes: list[dict], prefix: str) -> None:
        for i, n in enumerate(nodes):
            last = i == len(nodes) - 1
            lines.append(f"{prefix}{'└── ' if last else '├── '}{_text(n)}")
            walk(n.get("children", []), prefix + ("    " if last else "│   "))

    walk(tree["children"], "")
    return "\n".join(lines)


def main() -> None:
    from .db.session import make_engine, make_sessions

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", help="URL SQLAlchemy (défaut : $SERREIA_DB)")
    parser.add_argument("--zone")
    parser.add_argument("--debut", help="ISO, défaut : fin − 24 h")
    parser.add_argument("--fin", help="ISO, défaut : maintenant")
    parser.add_argument("--json", action="store_true", help="arbre JSON de l'API")
    args = parser.parse_args()

    def when(text: str | None, default: datetime) -> datetime:
        if text is None:
            return default
        ts = datetime.fromisoformat(text)
        return ts if ts.tzinfo else ts.replace(tzinfo=UTC)

    fin = when(args.fin, datetime.now(UTC))
    debut = when(args.debut, fin - timedelta(hours=24))
    sessions = make_sessions(make_engine(args.db))
    with sessions.begin() as s:
        reconcile(s, datetime.now(UTC))
        tree = build_tree(s, debut, fin, args.zone)
    print(json.dumps(tree, ensure_ascii=False, indent=1) if args.json else render_text(tree))


if __name__ == "__main__":
    main()
