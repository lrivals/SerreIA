"""Expected outcome of a scenario (docs/16 §2): `sim/scenarios/<nom>.attendus.yaml`.

    attendus:    # each entry must match at least `min` (default 1), at most `max` decisions
      - {nom: capteur figé, regle: securite.capteur_fige, zone: z1, de: J1 10:00, a: J1 11:00,
         alerte: figé}
      - {nom: dosage pH, regle: ph.dosage, zone: z2, de: J1 13:00, a: J1 14:30,
         actionneur: pompe_ph_down, action: on, max: 3}
    interdits:   # no decision may match
      - {nom: mildiou vu par une caméra, regle: maladie.mildiou.ventilation, preuve_vision: true}

An entry with `connu: <texte>` is a known gap of the system (docs/16 §6): it is reported
but does not fail the run, and its unexpected success is reported too (to remove `connu`).

Criteria of a decision: `regle`, `zone`, `statut`, `preuve_vision` (vision evidence or
not), window `de`/`a` (times of sim/scenario.py); `actionneur` (+ `action`, a value or a
list): a command of that actuator referencing the decision; `maintien_s`: that actuator
stays in that state at least this long; `alerte`: an alert of the zone containing this
text, published in the window (alone: an alert without a decision criterion).

`verifier` also checks the invariants of docs/16 §3 on the whole bus log: every message
decodes, every command references a decision published before it (versioned rule,
`config_version`), pumps always timed and within `duree_max_s`, a safety refusal traced
once while its cause lasts, no actuator switched off before `marche_min_s`, dosing pulses
spaced by `impulsion_s + melange_s`, consumption computed when the run was ingested.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from common.mqtt import Alert, Command, Decision, TopicKind, decode, parse_raison, parse_topic

from .scenario import Run, parse_time


@dataclass
class Bus:
    """The decoded bus log of a run, by kind."""

    decisions: list[Decision] = field(default_factory=list)
    commands: list[tuple[str, str, Command]] = field(default_factory=list)  # zone, actuator
    alerts: list[tuple[str, Alert]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @classmethod
    def of(cls, log: list[tuple[str, bytes]]) -> "Bus":
        bus = cls()
        for topic, payload in log:
            try:
                parsed = parse_topic(topic)
                msg = decode(topic, payload)
            except ValueError as e:
                bus.errors.append(f"{topic} : {e}")
                continue
            if parsed.kind is TopicKind.DECISION:
                bus.decisions.append(msg)
            elif parsed.kind is TopicKind.CMD and parsed.subject != "capture":
                bus.commands.append((parsed.scope, parsed.subject, msg))
            elif parsed.kind is TopicKind.ALERTE:
                bus.alerts.append((parsed.scope, msg))
        return bus

    def commands_of(self, decision_id: str) -> list[tuple[str, str, Command]]:
        return [c for c in self.commands if parse_raison(c[2].raison)[0] == decision_id]


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


def _window(entry: dict, debut: datetime) -> tuple[datetime | None, datetime | None]:
    de = parse_time(entry["de"], debut) if entry.get("de") is not None else None
    a = parse_time(entry["a"], debut) if entry.get("a") is not None else None
    return de, a


def _in(ts: datetime, de, a) -> bool:
    return (de is None or ts >= de) and (a is None or ts < a)


def _actions(entry: dict) -> set[str] | None:
    a = entry.get("action")
    return None if a is None else set(a if isinstance(a, list) else [a])


def _held(bus: Bus, zone: str, actuator: str, cmd: Command, until: datetime) -> float:
    """Seconds the actuator keeps the state of `cmd` (next command or end of the run)."""
    later = [c.ts for z, a, c in bus.commands if (z, a) == (zone, actuator) and c.ts > cmd.ts]
    return ((min(later) if later else until) - cmd.ts).total_seconds()


def matches(entry: dict, bus: Bus, debut: datetime, fin: datetime) -> list[str]:
    """What matches an entry: decision ids, or alert texts for an alert-only entry."""
    de, a = _window(entry, debut)
    zone = entry.get("zone")
    alerte = entry.get("alerte")
    alerts = [
        al for z, al in bus.alerts
        if (zone is None or z == zone) and _in(al.ts, de, a)
        and (alerte is None or str(alerte).lower() in al.message.lower())
    ]  # fmt: skip
    if not {"regle", "statut", "preuve_vision", "actionneur"} & entry.keys():
        return [al.message for al in alerts] if alerte is not None else []
    if alerte is not None and not alerts:
        return []
    out = []
    for d in bus.decisions:
        if entry.get("regle") and d.regle.id != entry["regle"]:
            continue
        if (zone and d.zone != zone) or not _in(d.ts, de, a):
            continue
        if entry.get("statut") and d.statut != entry["statut"]:
            continue
        if "preuve_vision" in entry and bool(d.preuves.vision) != bool(entry["preuve_vision"]):
            continue
        if entry.get("actionneur"):
            actions = _actions(entry)
            cmds = [
                (z, act, c) for z, act, c in bus.commands_of(d.id)
                if act == entry["actionneur"] and (actions is None or c.action in actions)
            ]  # fmt: skip
            if not cmds:
                continue
            hold = entry.get("maintien_s")
            if hold and not any(_held(bus, z, act, c, fin) >= hold for z, act, c in cmds):
                continue
        out.append(d.id)
    return out


@dataclass
class Resultat:
    ecarts: list[str] = field(default_factory=list)  # failures
    connus: list[str] = field(default_factory=list)  # known gaps, still there
    resolus: list[str] = field(default_factory=list)  # known gaps that no longer show

    @property
    def ok(self) -> bool:
        return not self.ecarts


def check_entries(raw: dict, bus: Bus, debut: datetime, fin: datetime) -> Resultat:
    res = Resultat()

    def report(e: dict, failed: bool, msg: str) -> None:
        if e.get("connu"):
            if failed:
                res.connus.append(f"{msg} — connu : {e['connu']}")
            else:
                res.resolus.append(f"« {e.get('nom', e)} » ne se produit plus (retirer `connu`)")
        elif failed:
            res.ecarts.append(msg)

    for e in raw.get("attendus") or []:
        found = matches(e, bus, debut, fin)
        hi = e.get("max")
        lo = e.get("min", 1 if hi is None else min(1, hi))
        want = f"{lo}" + (f"..{hi}" if hi is not None else "+")
        failed = len(found) < lo or (hi is not None and len(found) > hi)
        report(e, failed, f"attendu « {e.get('nom', e)} » : {len(found)} trouvé(s), {want} "
                          f"voulu(s) {found[:3]}")  # fmt: skip
    for e in raw.get("interdits") or []:
        found = matches(e, bus, debut, fin)
        report(e, bool(found), f"interdit « {e.get('nom', e)} » : {len(found)} {found[:3]}")
    return res


def invariants(bus: Bus, gh, run: Run | None = None) -> list[str]:
    """The common criteria of docs/16 §3, on every message of the run."""
    errors = [f"message invalide : {e}" for e in bus.errors[:10]]
    published: dict[str, Decision] = {}
    order = {}
    for i, d in enumerate(bus.decisions):
        published.setdefault(d.id, d)
        order.setdefault(d.id, i)
        if d.config_version is None:
            errors.append(f"{d.id} : config_version absente")

    for zone, actuator, c in bus.commands:
        did, _ = parse_raison(c.raison)
        if did is None or did not in published:
            errors.append(f"commande {zone}/{actuator} {c.ts:%d %H:%M} sans décision ({c.raison})")
        elif published[did].ts > c.ts:
            errors.append(f"commande {zone}/{actuator} publiée avant sa décision {did}")
        cfg = gh.cfg.actuator(zone, actuator)
        if cfg is not None and cfg.type.is_pump and c.action != "off":
            if c.duree_s is None:
                errors.append(f"pompe {zone}/{actuator} {c.ts:%d %H:%M} sans duree_s")
            elif cfg.duree_max_s is not None and c.duree_s > cfg.duree_max_s:
                errors.append(f"pompe {zone}/{actuator} {c.duree_s:g} s > {cfg.duree_max_s:g} s")

    # A safety refusal is traced once while its cause lasts: never two `bloquee_securite`
    # of the same rule in a row without another outcome in between.
    last: dict[tuple[str, str], str] = {}
    for d in bus.decisions:
        key = (d.zone, d.regle.id)
        if d.statut == "bloquee_securite" and last.get(key) == "bloquee_securite":
            errors.append(f"refus répété {d.zone} {d.regle.id} {d.ts:%d %H:%M} ({d.id})")
        last[key] = d.statut

    by_act: dict[tuple[str, str], list[Command]] = {}
    for zone, actuator, c in bus.commands:
        by_act.setdefault((zone, actuator), []).append(c)
    for (zone, actuator), cmds in by_act.items():
        cfg = gh.cfg.actuator(zone, actuator)
        if cfg is None:
            continue
        for prev, cur in zip(cmds, cmds[1:], strict=False):
            gap = (cur.ts - prev.ts).total_seconds()
            if (prev.action != "off" and prev.duree_s is None and cur.action == "off"
                    and cur.source != "safety" and gap < cfg.marche_min_s - 1):  # fmt: skip
                errors.append(f"{zone}/{actuator} arrêté après {gap:.0f} s < marche_min_s "
                              f"{cfg.marche_min_s:g} s ({cur.ts:%d %H:%M})")  # fmt: skip
        if cfg.impulsion_s:
            pulses = [c for c in cmds if c.action != "off"]
            spacing = cfg.impulsion_s + cfg.melange_s
            for prev, cur in zip(pulses, pulses[1:], strict=False):
                if (cur.ts - prev.ts).total_seconds() < spacing - 1:
                    errors.append(f"{zone}/{actuator} : impulsions à moins de {spacing:g} s "
                                  f"({cur.ts:%d %H:%M})")  # fmt: skip

    if run is not None and run.consommation is not None:
        for day, totals in run.consommation.items():
            if not totals.get("kwh"):
                errors.append(f"consommation du {day} non calculée")
    return errors


def verifier(run: Run, attendus: Path | dict | None = None, gh=None) -> Resultat:
    """The run against its expected outcome and the invariants (`ok`: no failure)."""
    from edge.controller.config import load_greenhouse

    gh = gh or load_greenhouse()
    if attendus is None:
        attendus = run.scenario.attendus_path
    raw = load(attendus) if isinstance(attendus, Path) else (attendus or {})
    bus = Bus.of(run.log)
    fin = run.sim.t if run.sim is not None else run.scenario.fin
    res = check_entries(raw, bus, run.scenario.debut, fin)
    res.ecarts[:0] = invariants(bus, gh, run)
    return res


def rapport(run: Run, res: Resultat) -> str:
    """Human summary of a run: counts, decisions by rule, consumption, errors."""
    bus = Bus.of(run.log)
    rules: dict[str, int] = {}
    for d in bus.decisions:
        rules[f"{d.regle.id} ({d.statut})"] = rules.get(f"{d.regle.id} ({d.statut})", 0) + 1
    lines = [
        f"scénario {run.scenario.nom} : {run.scenario.debut:%Y-%m-%d %H:%M} + "
        f"{run.scenario.duree_h:g} h, seed {run.scenario.seed}",
        f"{len(run.log)} messages, {len(bus.decisions)} décisions, {len(bus.commands)} "
        f"commandes, {len(bus.alerts)} alertes",
        "décisions par règle :",
        *(f"  {n:4d}  {k}" for k, n in sorted(rules.items())),
    ]
    for day, t in (run.consommation or {}).items():
        dli = ", ".join(f"{z} {v:.1f}" for z, v in (t.get("dli") or {}).items())
        lines.append(f"consommation {day} : {t['kwh']:.3f} kWh, {t['litres']:.1f} L, "
                     f"{t.get('cout') or 0:.2f} €, DLI (mol/m²) {dli or '—'}")  # fmt: skip
    lines.append("vérification : OK" if res.ok else f"vérification : {len(res.ecarts)} écart(s)")
    lines += [f"  ✖ {e}" for e in res.ecarts]
    lines += [f"  ⚠ {e}" for e in res.connus]
    lines += [f"  ✔ {e}" for e in res.resolus]
    return "\n".join(lines)
