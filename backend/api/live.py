"""`WS /ws/live` (docs/12 §3): the messages of the bus relayed to the browser, read-only."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["live"])


@router.websocket("/ws/live")
async def live(ws: WebSocket) -> None:
    await ws.accept()
    hub = ws.app.state.live
    if hub is None:  # no bus (--mqtt none): nothing will come
        await ws.send_json(dict(kind="info", zone=None, subject=None,
                                payload={"message": "pas de connexion MQTT"}))  # fmt: skip
    async with _subscription(hub) as queue:
        closed = asyncio.create_task(_until_closed(ws))
        try:
            while True:
                get = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait({get, closed}, return_when=asyncio.FIRST_COMPLETED)
                if closed in done:
                    get.cancel()
                    return
                await ws.send_json(get.result())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            closed.cancel()


async def _until_closed(ws: WebSocket) -> None:
    """Reads (and ignores) what the client sends, until it leaves."""
    try:
        while True:
            await ws.receive_text()
    except (WebSocketDisconnect, RuntimeError):
        return


@asynccontextmanager
async def _subscription(hub):
    if hub is None:
        yield asyncio.Queue()
        return
    async with hub.subscription() as queue:
        yield queue
