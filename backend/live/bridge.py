"""MQTT → WebSocket bridge (docs/12 §3, `WS /ws/live`).

`LiveHub` subscribes to the topics of the contract on the bus of the API (MqttPublisher,
LoopbackBus…), validates every message with `common.mqtt.decode` and relays it to the
connected browsers as `{kind, zone, subject, payload}`. MQTT callbacks run on the client
thread: events reach each WebSocket through its own event loop
(`call_soon_threadsafe`) and a bounded queue; a client too slow to read loses events
rather than holding the bus.
"""

import asyncio
import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from pydantic import BaseModel

from common.mqtt import SUBSCRIPTIONS, TopicKind, decode, parse_topic

log = logging.getLogger(__name__)

QUEUE_SIZE = 1000


def event(topic: str, payload: bytes | str) -> dict | None:
    """The UI event of an MQTT message; None for an invalid one."""
    try:
        parsed = parse_topic(topic)
        message = decode(topic, payload)
    except ValueError as e:
        log.debug("message ignoré %s : %s", topic, e)
        return None
    status = parsed.kind is TopicKind.STATUS
    return dict(
        kind=parsed.kind.value,
        zone=None if status else parsed.scope,
        subject=parsed.scope if status else parsed.subject,
        payload=message.model_dump(mode="json") if isinstance(message, BaseModel) else message,
    )


class LiveHub:
    def __init__(self):
        self._lock = threading.Lock()
        self._clients: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
        self.relayed = 0

    def attach(self, bus) -> None:
        """`bus`: anything with `subscribe(pattern, handler)`."""
        for pattern in SUBSCRIPTIONS.values():
            bus.subscribe(pattern, self.on_message)

    @property
    def clients(self) -> int:
        return len(self._clients)

    def on_message(self, topic: str, payload: bytes | str) -> None:
        e = event(topic, payload)
        if e is None:
            return
        with self._lock:
            clients = list(self._clients)
        for loop, queue in clients:
            try:
                loop.call_soon_threadsafe(_put, queue, e)
            except RuntimeError:  # loop closed: the client is going away
                pass
        self.relayed += 1

    @asynccontextmanager
    async def subscription(self) -> AsyncIterator[asyncio.Queue]:
        client = (asyncio.get_running_loop(), asyncio.Queue(QUEUE_SIZE))
        with self._lock:
            self._clients.add(client)
        try:
            yield client[1]
        finally:
            with self._lock:
                self._clients.discard(client)


def _put(queue: asyncio.Queue, e: dict) -> None:
    try:
        queue.put_nowait(e)
    except asyncio.QueueFull:
        pass
