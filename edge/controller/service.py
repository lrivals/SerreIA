"""Greenhouse controller (docs/06 §4, docs/10): levels 0 → 2, decisions, commands.

    python -m edge.controller [--mqtt none] [--config edge/controller/serre.yaml]

Every tick (10 s), for each zone of `serre.yaml`:
1. proposals of the safety level (`safety.watch`), the risk index (`risk`), the forecast
   (`forecast.Level2`, when a model exists), the regulation rules (`rules`) and the
   "classification → action" rules (`vision_rules`);
2. arbitration per actuator: a safety "off" always wins, otherwise the "on" of the highest
   priority; orders matching the real state (`etat/`) or a command still unconfirmed are
   dropped, so routines produce one decision per regulation cycle, not one per tick;
3. every remaining order goes through `safety.check` (refused → decision
   `bloquee_securite` + alert, shortened → noted);
4. publication: `serre/<zone>/decision` first, then the `Command`s whose `raison` is
   "<decision id> | <text>", the capture requests, then the alerts (once while their
   condition holds, an info when it ends). Plant health states ("plante:z1-A1 malade") are
   only labels of the decision: the server applies them.

Life cycle (docs/10 §4): a proposal with `validation` gives a decision `proposee` (its
`ordres`, no command) that expires after `regles.expiration_s`. A decision received on
`serre/+/decision` with the status `validee` (the user validated a proposal of the
controller or of the agent, or a manual action) runs at the next tick through
`safety.check`, and is published again under the same id, `executee` or
`bloquee_securite`; `rejetee` forgets the proposal.
"""

import argparse
import logging
import signal
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from common.mqtt import (
    SUBSCRIPTIONS,
    Alert,
    CaptureRequest,
    Decision,
    TopicKind,
    alert_topic,
    capture_topic,
    cmd_topic,
    decision_topic,
    decode,
    parse_topic,
)

from . import risk, safety
from .config import DEFAULT_CONFIG, ConfigWatcher, Greenhouse
from .context import Ctx, make_ctx
from .decisions import DecisionFactory, Order, Proposal
from .forecast import Level2, load_forecaster
from .rules import Rules
from .state import GreenhouseState, Pending, ZoneState
from .vision_rules import VisionRules

log = logging.getLogger("controller")

NODE = "pi-controller"
PENDING_TIMEOUT = timedelta(seconds=120)  # an unconfirmed command is re-sent after this
MAX_DONE = 1000  # ids of validated decisions already run, kept against redelivery


@dataclass
class Controller:
    config: ConfigWatcher | Greenhouse
    publisher: object = None  # edge.publisher.Publisher; None: outputs only returned
    level2: Level2 = field(default_factory=lambda: Level2(None))
    state: GreenhouseState = field(default_factory=GreenhouseState)

    def __post_init__(self):
        self.rules = Rules()
        self.vision_rules = VisionRules()
        self.factory = DecisionFactory()
        self.alerts: dict[str, tuple[str, str | None]] = {}  # key -> (zone, end message)
        self.latched: set[str] = set()  # Proposal.key already acted on (docs/10 §5)
        self.proposals: dict[str, Decision] = {}  # id -> decision `proposee` waiting
        self.validated: list[Decision] = []  # received `validee`, run at the next tick
        self.done: dict[str, None] = {}  # ids of validated decisions already run
        self.lock = threading.Lock()
        self.published: list[tuple[str, object]] = []
        gh = self.greenhouse
        self.state.tz = ZoneInfo(gh.cfg.fuseau)
        self.state.lux_to_ppfd = gh.cfg.lumiere.lux_vers_ppfd

    @property
    def greenhouse(self) -> Greenhouse:
        return self.config.get() if isinstance(self.config, ConfigWatcher) else self.config

    # --- input --------------------------------------------------------------------------

    def on_message(self, topic: str, payload: bytes) -> None:
        with self.lock:
            try:
                if parse_topic(topic).kind is TopicKind.DECISION:
                    self.on_decision(decode(topic, payload))
                else:
                    self.state.on_message(topic, payload)
            except ValueError as e:
                log.warning("message ignoré %s : %s", topic, e)

    def on_decision(self, d: Decision) -> None:
        """Answers of the user or the agent; the controller's own messages are ignored."""
        if d.statut == "validee" and d.id not in self.done:
            self.validated.append(d)
        elif d.statut in ("rejetee", "expiree"):
            self.proposals.pop(d.id, None)

    def subscribe(self) -> None:
        kinds = (TopicKind.CAPTEUR, TopicKind.ETAT, TopicKind.STATUS, TopicKind.VISION)
        for kind in (*kinds, TopicKind.DECISION):
            self.publisher.subscribe(SUBSCRIPTIONS[kind], self.on_message)

    # --- tick ---------------------------------------------------------------------------

    def tick(self, now: datetime | None = None) -> list[tuple[str, object]]:
        now = now or datetime.now(UTC)
        with self.lock:
            gh = self.greenhouse
            ctxs = {z.id: make_ctx(gh, self.state.zone(z.id), now) for z in gh.cfg.zones}
            proposals = safety.watch(self.state, ctxs)
            for ctx in ctxs.values():
                proposals += risk.mildew(ctx)
                proposals += self.level2.evaluate(ctx)
                proposals += self.rules.evaluate(ctx)
                proposals += self.vision_rules.evaluate(ctx)
            out = self._lifecycle(ctxs, now)
            out += self._execute(gh, ctxs, proposals, now)
        for topic, message in out:
            if self.publisher is not None:
                self.publisher.publish(topic, message)
        self.published += out
        return out

    def _arbitrate(self, ctxs: dict[str, Ctx], proposals: list[Proposal], now: datetime):
        """Kept orders per proposal (index -> orders)."""
        wanted: dict[tuple[str, str], list[tuple[int, Order]]] = {}
        for i, p in enumerate(proposals):
            if p.validation:  # nothing runs before the user answers
                continue
            for o in p.orders:
                wanted.setdefault((p.zone, o.actuator), []).append((i, o))
        kept: dict[int, list[Order]] = {}
        for (zone, act), items in wanted.items():
            zs = ctxs[zone].zs
            offs = [(i, o) for i, o in items if not o.is_on]
            ons = [(i, o) for i, o in items if o.is_on]
            safety_off = [(i, o) for i, o in offs if proposals[i].type == "securite"]
            if safety_off:
                choice = safety_off[0]
            elif ons:
                choice = max(ons, key=lambda io: proposals[io[0]].priority)
                i, o = choice
                if _matches(zs, act, o, now):
                    if o.duree_s is None:  # an untimed "on": the new rule now owns it
                        zs.owner[act] = proposals[i].regle.id
                    continue
            else:
                choice = offs[0]
            i, o = choice
            if not o.is_on and not zs.actuator_on(act) and not _pending_on(zs, act, now):
                continue
            if _matches(zs, act, o, now):
                continue
            kept.setdefault(i, []).append(o)
        return kept

    def _execute(self, gh: Greenhouse, ctxs, proposals: list[Proposal], now: datetime):
        out: list[tuple[str, object]] = []
        kept = self._arbitrate(ctxs, proposals, now)
        active = set()
        for i, p in enumerate(proposals):
            ctx = ctxs[p.zone]
            if p.key is not None:
                active.add(p.key)
            alert = None
            if p.alerte is not None:
                active.add(p.alerte.key)
                if p.alerte.key not in self.alerts:
                    self.alerts[p.alerte.key] = (p.zone, p.alerte.fin)
                    alert = Alert(
                        ts=now,
                        niveau=p.alerte.niveau,
                        message=p.alerte.message,
                        source=f"{p.origine}/{p.regle.id}",
                    )
            if p.validation:
                out += self._propose(gh, p, alert, now)
                continue
            first = p.key is None or p.key not in self.latched
            plantes = p.plantes if first else []
            consigne = p.consigne if first else None
            if p.key is not None and (plantes or consigne):
                self.latched.add(p.key)
            orders = kept.get(i, [])
            verdicts = [safety.check(ctx, o) for o in orders]
            refused = [v for v in verdicts if not v.ok]
            for v in refused:
                key = f"{p.zone}/bloque/{p.regle.id}/{v.order.actuator}/{v.limite}"
                active.add(key)
                if key in self.alerts:
                    verdicts.remove(v)  # already reported: no new decision
                else:
                    self.alerts[key] = (p.zone, None)
            effects = (p.captures, plantes, consigne, alert)
            out += self._publish(gh, ctx, p, verdicts, *effects, now)

        for key in [k for k in self.alerts if k not in active]:
            zone, fin = self.alerts.pop(key)
            if fin:
                out.append(
                    (
                        alert_topic(zone),
                        Alert(ts=now, niveau="info", message=fin, source="controller"),
                    )
                )
        self.latched &= active
        return out

    def _publish(
        self,
        gh: Greenhouse,
        ctx: Ctx,
        p: Proposal,
        verdicts: list[safety.Verdict],
        captures: list[str],
        plantes: list[tuple[str, str]],
        consigne,
        alert: Alert | None,
        now: datetime,
        decision: Decision | None = None,
    ) -> list[tuple[str, object]]:
        """Decision, then its commands, capture requests and alerts. `decision`: a validated
        one, published again under its id instead of a new decision."""
        ok = [v for v in verdicts if v.ok]
        refused = [v for v in verdicts if not v.ok]
        if not (ok or refused or alert or captures or plantes or consigne):
            return []
        labels = [f"cmd:{v.order.label()}" for v in ok] + (["alerte"] if alert else [])
        labels += [f"bloquee:{v.order.label()} ({v.limite})" for v in refused]
        labels += [f"capture:{c}" for c in captures]
        labels += [f"plante:{e} {etat}" for e, etat in plantes]
        if consigne is not None:
            labels.append(f"consigne:{consigne.label()}")
        explication = decision.explication if decision else p.explication
        notes = [v.note for v in verdicts if v.note and v.ok]
        if notes:
            explication += f" [sécurité : {'; '.join(notes)}]"
        if refused:
            explication += " [bloqué : " + "; ".join(v.note or v.limite for v in refused) + "]"
        statut = "bloquee_securite" if refused and not ok else "executee"
        actions = [v.order for v in verdicts]
        ordres = [o for o in map(Order.ordre, actions) if o is not None]
        ordres += [o for o in p.ordres() if o.kind != "actionneur"]
        if decision is None:
            decision = self.factory.decision(
                p, now, gh.version, labels, statut, explication, ordres
            )
        else:
            update = dict(actions=labels, statut=statut, explication=explication)
            decision = decision.model_copy(update=update)
        out: list[tuple[str, object]] = [(decision_topic(p.zone), decision)]
        source = "safety" if p.origine == "safety" else p.origine.partition(":")[0]
        zs = ctx.zs
        for v in ok:
            cmd = self.factory.command(v.order, decision, now, source)
            cmd.validate_for(v.order.actuator)
            out.append((cmd_topic(p.zone, v.order.actuator), cmd))
            zs.pending[v.order.actuator] = Pending(v.order.action, v.order.valeur, now)
            if v.order.is_on:
                zs.last_on[v.order.actuator] = now
                if v.order.duree_s is None:
                    zs.owner[v.order.actuator] = p.regle.id
        for cam in captures:
            out.append((capture_topic(p.zone), CaptureRequest(ts=now, source=source, camera=cam)))
        if consigne is not None:
            zs.consignes[consigne.nom] = (consigne.delta, now + timedelta(seconds=consigne.duree_s))
        if ok or captures:
            zs.rule_fired[p.regle.id] = now
        if alert is not None:
            out.append((alert_topic(p.zone), alert))
        for v in refused:
            out.append(
                (
                    alert_topic(p.zone),
                    Alert(
                        ts=now,
                        niveau="warning",
                        source=f"safety/{v.limite}",
                        message=f"{p.zone} : {v.order.label()} bloqué ({v.note or v.limite}), "
                        f"décision {decision.id}",
                    ),
                )
            )
        log.info("%s [%s] %s", decision.id, decision.statut, decision.explication)
        return out

    def _propose(self, gh: Greenhouse, p: Proposal, alert: Alert | None, now: datetime):
        """Decision `proposee`: its orders wait for the user; the alert goes out now."""
        out: list[tuple[str, object]] = []
        if p.key is None or p.key not in self.latched:
            if p.key is not None:
                self.latched.add(p.key)
            ordres = p.ordres()
            labels = [f"proposee:{o.label()}" for o in ordres] + (["alerte"] if alert else [])
            expire = now + timedelta(seconds=gh.regles.expiration_s)
            d = self.factory.decision(p, now, gh.version, labels, "proposee", None, ordres, expire)
            self.proposals[d.id] = d
            out.append((decision_topic(p.zone), d))
            log.info("%s [proposee] %s", d.id, d.explication)
        if alert is not None:
            out.append((alert_topic(p.zone), alert))
        return out

    def _lifecycle(self, ctxs: dict[str, Ctx], now: datetime) -> list[tuple[str, object]]:
        """Expired proposals, then the validated decisions received since the last tick."""
        out: list[tuple[str, object]] = []
        for did, d in list(self.proposals.items()):
            if d.expire is not None and now >= d.expire:
                del self.proposals[did]
                out.append((decision_topic(d.zone), d.model_copy(update=dict(statut="expiree"))))
        validated, self.validated = self.validated, []
        for d in validated:
            if d.id in self.done:
                continue
            self.done[d.id] = None
            while len(self.done) > MAX_DONE:
                del self.done[next(iter(self.done))]
            self.proposals.pop(d.id, None)
            ctx = ctxs.get(d.zone)
            if ctx is None:
                log.warning("décision validée %s : zone inconnue %s", d.id, d.zone)
                continue
            if d.expire is not None and now >= d.expire:
                out.append((decision_topic(d.zone), d.model_copy(update=dict(statut="expiree"))))
                continue
            out += self._run_validated(ctx, d, now)
        return out

    def _run_validated(self, ctx: Ctx, d: Decision, now: datetime) -> list[tuple[str, object]]:
        p = Proposal(
            zone=d.zone,
            regle=d.regle,
            niveau=d.niveau if isinstance(d.niveau, int) else 1,
            type=d.type,
            explication=d.explication,
            origine=d.origine,
            captures=[o.subject for o in d.ordres if o.kind == "camera"],
            plantes=[(o.subject, o.action) for o in d.ordres if o.kind == "plante"],
        )
        orders = [Order.of(o) for o in d.ordres if o.kind == "actionneur"]
        verdicts = [safety.check(ctx, o) for o in orders]
        effects = (p.captures, p.plantes, None, None)
        out = self._publish(self.greenhouse, ctx, p, verdicts, *effects, now, decision=d)
        if not out:  # nothing to run (empty decision): executed as is
            out = [(decision_topic(d.zone), d.model_copy(update=dict(statut="executee")))]
        return out


def _matches(zs: ZoneState, act: str, o: Order, now: datetime) -> bool:
    """The actuator is already (or about to be) in the state the order asks for."""
    p = zs.pending.get(act)
    if p is not None and now - p.ts < PENDING_TIMEOUT:
        return p.action == o.action and (o.action != "pwm" or p.valeur == o.valeur)
    s = zs.actuators.get(act)
    if s is None:
        return o.action == "off"
    if o.action == "off":
        return s.action == "off"
    return s.action == o.action and (o.action != "pwm" or s.valeur == o.valeur)


def _pending_on(zs: ZoneState, act: str, now: datetime) -> bool:
    p = zs.pending.get(act)
    return p is not None and p.action != "off" and now - p.ts < PENDING_TIMEOUT


def build(config: Path = DEFAULT_CONFIG, publisher=None) -> Controller:
    watcher = ConfigWatcher(config)
    model = watcher.greenhouse.cfg.prevision.modele
    forecaster = load_forecaster(watcher.greenhouse.cfg.resolve(model) if model else None)
    return Controller(watcher, publisher, Level2(forecaster))


def main() -> None:
    from edge.publisher import make_publisher
    from edge.sdnotify import sd_notify

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--mqtt", choices=["broker", "none"], default="broker")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--periode", type=float, default=10.0, help="tick (s)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    pub = make_publisher(args.mqtt, NODE, args.host, args.port)
    ctl = build(args.config, pub)
    ctl.subscribe()
    sd_notify("READY=1")
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    try:
        while not stop.wait(args.periode):
            ctl.tick()
            sd_notify("WATCHDOG=1")
    except KeyboardInterrupt:
        pass
    finally:
        pub.close()


if __name__ == "__main__":
    main()
