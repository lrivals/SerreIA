"""MQTT publication of the Pi services (docs/01 §2): paho client or dry run without broker."""

import json
import logging
from collections.abc import Callable
from typing import Protocol

from common.mqtt import TOPIC_POLICY, encode, parse_topic, status_topic
from common.mqtt.schemas import NodeStatus, _Message

log = logging.getLogger(__name__)

Handler = Callable[[str, bytes], None]


class Publisher(Protocol):
    def publish(self, topic: str, message: _Message | NodeStatus) -> None: ...

    def subscribe(self, pattern: str, handler: Handler) -> None: ...

    def close(self) -> None: ...


def _policy(topic: str):
    return TOPIC_POLICY[parse_topic(topic).kind]


class DryRunPublisher:
    """No broker: messages are logged (PC tests); subscriptions receive nothing."""

    def __init__(self, node: str):
        self.node = node
        self.published: list[tuple[str, bytes]] = []

    def publish(self, topic: str, message) -> None:
        payload = encode(message)
        self.published.append((topic, payload))
        try:
            text = json.dumps(json.loads(payload), ensure_ascii=False)
        except ValueError:
            text = payload.decode()
        log.info("[mqtt sec] %s %s", topic, text)

    def subscribe(self, pattern: str, handler: Handler) -> None:
        log.info("[mqtt sec] abonnement ignoré : %s", pattern)

    def close(self) -> None:
        pass


class LoopbackBus:
    """In-memory broker: the simulator, the controller and the tests share one process.

    Retained messages (etat/, status) are replayed to late subscribers, as mosquitto does.
    Delivery is synchronous; messages published from a handler are queued and delivered
    after it returns, so the order seen by every subscriber is the publication order.
    """

    def __init__(self):
        self.subs: list[tuple[str, Handler]] = []
        self.retained: dict[str, bytes] = {}
        self.log: list[tuple[str, bytes]] = []
        self._queue: list[tuple[str, bytes]] = []
        self._delivering = False

    def publish(self, topic: str, payload: bytes) -> None:
        self.log.append((topic, payload))
        if _policy(topic).retain:
            self.retained[topic] = payload
        self._queue.append((topic, payload))
        if self._delivering:
            return
        self._delivering = True
        try:
            while self._queue:
                t, p = self._queue.pop(0)
                for pattern, handler in list(self.subs):
                    if _matches(pattern, t):
                        try:
                            handler(t, p)
                        except Exception:
                            log.exception("traitement de %s", t)
        finally:
            self._delivering = False

    def subscribe(self, pattern: str, handler: Handler) -> None:
        self.subs.append((pattern, handler))
        for t, p in list(self.retained.items()):
            if _matches(pattern, t):
                handler(t, p)


def _matches(pattern: str, topic: str) -> bool:
    import paho.mqtt.client as mqtt

    return mqtt.topic_matches_sub(pattern, topic)


class LoopbackPublisher:
    """Publisher on a LoopbackBus, with the `online` / `offline` status of MqttPublisher."""

    def __init__(self, node: str, bus: LoopbackBus):
        self.node, self.bus = node, bus
        self.publish(status_topic(node), "online")

    def publish(self, topic: str, message) -> None:
        self.bus.publish(topic, encode(message))

    def subscribe(self, pattern: str, handler: Handler) -> None:
        self.bus.subscribe(pattern, handler)

    def close(self) -> None:
        self.publish(status_topic(self.node), "offline")


class MqttPublisher:
    """paho-mqtt 2 client: QoS / retain from the contract, LWT `status = offline`,
    `online` published at every (re)connection, subscriptions restored on reconnect."""

    def __init__(self, node: str, host: str = "localhost", port: int = 1883, keepalive: int = 60):
        import paho.mqtt.client as mqtt

        self.node, self.handlers = node, {}
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=node)
        self.client.will_set(status_topic(node), encode("offline"), qos=1, retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.connect_async(host, port, keepalive)
        self.client.loop_start()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if reason_code.is_failure:
            log.error("connexion MQTT refusée : %s", reason_code)
            return
        log.info("MQTT connecté")
        self.publish(status_topic(self.node), "online")
        for pattern in self.handlers:
            client.subscribe(pattern, qos=1)

    def _on_message(self, client, userdata, msg) -> None:
        import paho.mqtt.client as mqtt

        for pattern, handler in self.handlers.items():
            if mqtt.topic_matches_sub(pattern, msg.topic):
                try:
                    handler(msg.topic, msg.payload)
                except Exception:
                    log.exception("traitement de %s", msg.topic)

    def publish(self, topic: str, message) -> None:
        p = _policy(topic)
        self.client.publish(topic, encode(message), qos=p.qos, retain=p.retain)

    def subscribe(self, pattern: str, handler: Handler) -> None:
        self.handlers[pattern] = handler
        if self.client.is_connected():
            self.client.subscribe(pattern, qos=1)

    def close(self) -> None:
        info = self.client.publish(status_topic(self.node), encode("offline"), qos=1, retain=True)
        try:
            info.wait_for_publish(timeout=2)
        except (RuntimeError, ValueError):  # not connected: the broker's LWT will do it
            pass
        self.client.loop_stop()
        self.client.disconnect()


def make_publisher(mode: str, node: str, host: str, port: int, keepalive: int = 60) -> Publisher:
    if mode == "none":
        return DryRunPublisher(node)
    return MqttPublisher(node, host, port, keepalive)
