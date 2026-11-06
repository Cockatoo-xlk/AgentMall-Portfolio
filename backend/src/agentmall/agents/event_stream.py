"""Bounded, read-only delivery of the existing public RunEvent projection."""

import asyncio
import json

from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse

from agentmall.agents.run_service import event_snapshot
from agentmall.identity.routes import bearer, current_actor
from agentmall.infra.errors import DomainError

BATCH_SIZE = 50
WINDOW_SECONDS = 25
HEARTBEAT_SECONDS = 5
TERMINAL = {"COMPLETED", "PARTIAL", "FAILED"}


def frame(kind, data, seq=None):
    cursor = f"id: {seq}\n" if seq is not None else ""
    return f"{cursor}event: {kind}\ndata: {json.dumps(jsonable_encoder(data))}\n\n"


async def stream_events(request, actor, run_id, after_seq):
    # Establish HTTP authorization before sending headers.
    first = await event_snapshot(request.app, actor, run_id, after_seq, BATCH_SIZE)
    credential = await bearer(request)

    async def generate():
        loop = asyncio.get_running_loop()
        deadline = loop.time() + WINDOW_SECONDS
        heartbeat = loop.time() + HEARTBEAT_SECONDS
        cursor = after_seq
        snapshot = first
        previous_status = None
        while loop.time() < deadline and not await request.is_disconnected():
            if snapshot is None:
                try:
                    # Expired tokens, disabled users and changed store membership
                    # cannot keep reading via a previously opened connection.
                    async with asyncio.timeout(max(0, deadline - loop.time())):
                        current = await current_actor(request, credential)
                        snapshot = await event_snapshot(
                            request.app, current, run_id, cursor, BATCH_SIZE
                        )
                except DomainError as exc:
                    if exc.status == 401:
                        yield frame("auth_expired", {})
                    elif exc.status in {403, 404}:
                        yield frame("stream_denied", {"status": exc.status})
                    else:
                        raise
                    return
                except TimeoutError:
                    return
            page, status = snapshot
            snapshot = None
            for event in page["items"]:
                yield frame("run_event", event, event["seq"])
            cursor = page["next_seq"]
            if len(page["items"]) == BATCH_SIZE:
                continue
            if status != previous_status:
                yield frame("run_status", {"status": status})
                previous_status = status
            if status in TERMINAL:
                return
            if loop.time() >= heartbeat:
                yield ": heartbeat\n\n"
                heartbeat = loop.time() + HEARTBEAT_SECONDS
            interval = 1.5 if status == "WAITING_INPUT" else 0.5
            await asyncio.sleep(min(interval, max(0, deadline - loop.time())))

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
    )
