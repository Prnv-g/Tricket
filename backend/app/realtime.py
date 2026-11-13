import asyncio
import json
from collections import defaultdict
from contextlib import suppress

from fastapi import WebSocket, WebSocketDisconnect
from redis.exceptions import RedisError

from .auth import require_origin, session
from .config import EVENT
from .errors import Problem
from .inventory import prefix
from .queue_service import status
from .redis_client import redis

# Each local connection has a bounded mailbox. Version gaps trigger snapshots.
subscribers = defaultdict(set)


async def listen():
    while True:
        try:
            async with redis.pubsub() as pubsub:
                await pubsub.psubscribe("event:*:seat-events", "event:*:queue-events")
                async for message in pubsub.listen():
                    if message["type"] != "pmessage":
                        continue
                    channel, data = message["channel"], message["data"]
                    for mailbox in tuple(subscribers.get(channel, ())):
                        if mailbox.full():
                            with suppress(asyncio.QueueEmpty):
                                mailbox.get_nowait()
                        mailbox.put_nowait(data)
        except RedisError:
            await asyncio.sleep(.75)


async def stream(websocket: WebSocket, event=EVENT, queue=False):
    try:
        require_origin(websocket, required=True)
        sid = session(websocket)
    except Problem:
        await websocket.close(code=1008)
        return
    if event != EVENT:
        await websocket.close(code=1008)
        return
    channel = prefix(event) + ("queue-events" if queue else "seat-events")
    mailbox = asyncio.Queue(maxsize=32)
    subscribers[channel].add(mailbox)
    await websocket.accept()
    receive = asyncio.create_task(websocket.receive())
    try:
        if queue:
            await websocket.send_json(await status(event, sid))
        else:
            await websocket.send_json({"hello": True})
        while True:
            next_message = asyncio.create_task(mailbox.get())
            try:
                done, _ = await asyncio.wait({receive, next_message}, timeout=15, return_when=asyncio.FIRST_COMPLETED)
                if receive in done:
                    if receive.result()["type"] == "websocket.disconnect":
                        break
                    receive = asyncio.create_task(websocket.receive())
                if queue:
                    await websocket.send_json(await status(event, sid))
                elif next_message in done:
                    await websocket.send_json(json.loads(next_message.result()))
                elif not done:
                    await websocket.send_json({"ping": True})
            finally:
                if not next_message.done():
                    next_message.cancel()
                    with suppress(asyncio.CancelledError):
                        await next_message
    except (WebSocketDisconnect, RuntimeError, RedisError, OSError):
        with suppress(RuntimeError, OSError):
            await websocket.close(code=1012)
    finally:
        receive.cancel()
        with suppress(asyncio.CancelledError, RuntimeError):
            await receive
        subscribers[channel].discard(mailbox)
