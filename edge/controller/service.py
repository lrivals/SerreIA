"""Greenhouse controller (docs/06 §4, docs/10): levels 0 → 2, decisions, commands.

    python -m edge.controller [--mqtt none] [--config edge/controller/serre.yaml]

Every tick (10 s), for each zone of `serre.yaml`:
1. proposals of the safety level (`safety.watch`), the risk index (`risk`), the forecast
   (`forecast.Level2`, when a model exists) and the regulation rules (`rules`);
2. arbitration per actuator: a safety "off" always wins, otherwise the "on" of the highest
   priority; orders matching the real state (`etat/`) or a command still unconfirmed are
   dropped, so routines produce one decision per regulation cycle, not one per tick;
3. every remaining order goes through `safety.check` (refused → decision
   `bloquee_securite` + alert, shortened → noted);
4. publication: `serre/<zone>/decision` first, then the `Command`s whose `raison` is
   "<decision id> | <text>", then the alerts (once while their condition holds, an info
   when it ends).
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
    TopicKind,
    alert_topic,
    cmd_topic,
    decision_topic,
)

from . import risk, safety
from .config import DEFAULT_CONFIG, ConfigWatcher, Greenhouse
from .context import Ctx, make_ctx
from .decisions import DecisionFactory, Order, Proposal
from .forecast import Level2, load_forecaster
from .rules import Rules
from .state import GreenhouseState, Pending, ZoneState

log = logging.getLogger("controller")

NODE = "pi-controller"
PENDING_TIMEOUT = timedelta(seconds=120)  # an unconfirmed command is re-sent after this


@dataclass
class Controller:
    config: ConfigWatcher | Greenhouse
    publisher: object = None  # edge.publisher.Publisher; None: outputs only returned
    level2: Level2 = field(default_factory=lambda: Level2(None))
    state: GreenhouseState = field(default_factory=GreenhouseState)

    def __post_init__(self):
        self.rules = Rules()
        self.factory = DecisionFactory()
        self.alerts: dict[str, tuple[str, str | None]] = {}  # key -> (zone, end message)
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
                self.state.on_message(topic, payload)
            except ValueError as e:
                log.warning("message ignoré %s : %s", topic, e)

    def subscribe(self) -> None:
        for kind in (TopicKind.CAPTEUR, TopicKind.ETAT, TopicKind.STATUS, TopicKind.VISION):
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
            out = self._execute(gh, ctxs, proposals, now)
        for topic, message in out:
            if self.publisher is not None:
                self.publisher.publish(topic, message)
        self.published += out
        return out

    def _arbitrate(self, ctxs: dict[str, Ctx], proposals: list[Proposal], now: datetime):
        """Kept orders per proposal (index -> orders)."""
        wanted: dict[tuple[str, str], list[tuple[int, Order]]] = {}
        for i, p in enumerate(proposals):
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
            orders = kept.get(i, [])
            verdicts = [safety.check(ctx, o) for o in orders]
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
            refused = [v for v in verdicts if not v.ok]
            for v in refused:
                key = f"{p.zone}/bloque/{p.regle.id}/{v.order.actuator}/{v.limite}"
                active.add(key)
                if key in self.alerts:
                    verdicts.remove(v)  # already reported: no new decision
                else:
                    self.alerts[key] = (p.zone, None)
            ok = [v for v in verdicts if v.ok]
            refused = [v for v in verdicts if not v.ok]
            if not ok and not refused and alert is None:
                continue

            labels = [f"cmd:{v.order.label()}" for v in ok] + (["alerte"] if alert else [])
            labels += [f"bloquee:{v.order.label()} ({v.limite})" for v in refused]
            explication = p.explication
            notes = [v.note for v in verdicts if v.note and v.ok]
            if notes:
                explication += f" [sécurité : {'; '.join(notes)}]"
            if refused:
                explication += " [bloqué : " + "; ".join(v.note or v.limite for v in refused) + "]"
            statut = "bloquee_securite" if refused and not ok else "executee"
            decision = self.factory.decision(p, now, gh.version, labels, statut, explication)
            out.append((decision_topic(p.zone), decision))
            source = "safety" if p.origine == "safety" else "controller"
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
            if ok:
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

        for key in [k for k in self.alerts if k not in active]:
            zone, fin = self.alerts.pop(key)
            if fin:
                out.append(
                    (
                        alert_topic(zone),
                        Alert(ts=now, niveau="info", message=fin, source="controller"),
                    )
                )
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
