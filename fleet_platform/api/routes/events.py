"""Live job-event push endpoint (#756 / ARC-11).

``GET /api/v1/events/jobs/stream`` is the *subscribe* half of the job-event
push channel. It opens a Server-Sent Events stream (``text/event-stream``) and
forwards every message published to the ``kri:job_events`` Redis channel (see
``fleet_platform/services/job_events.py``) to the client as a ``data:`` line.

This lets the frontend invalidate the affected React Query caches on *push*
instead of polling on fixed timers, collapsing ~40 ``refetchInterval`` loops
into a single push connection (with a slow safety-net poll left in place).

Notes:
  * Auth reuses ``require_role`` like every other route. EventSource cannot send
    an ``Authorization`` header, so the frontend consumes this with
    ``fetch`` + a ``ReadableStream`` reader (same pattern as ``api/llm.ts``).
  * Periodic ``: keepalive`` comments keep proxies/load-balancers from idling
    the connection out.
  * Client disconnects are detected via ``request.is_disconnected()`` and the
    pub/sub subscription is always torn down in ``finally``.
"""

from __future__ import annotations

import asyncio
import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from fleet_platform.core.auth import require_role
from fleet_platform.core.redis import get_redis
from fleet_platform.services.job_events import JOB_EVENTS_CHANNEL

router = APIRouter(prefix="/api/v1/events", tags=["events"])

logger = logging.getLogger(__name__)

# How long to wait for a pub/sub message before emitting a keepalive comment.
# Doubles as the disconnect-detection cadence.
_HEARTBEAT_SECONDS = 15.0


@router.get("/jobs/stream")
async def stream_job_events(
    request: Request,
    claims: dict = Depends(require_role("viewer", "operator", "admin")),
    redis: aioredis.Redis = Depends(get_redis),
) -> StreamingResponse:
    """Stream job-state transitions to the client as SSE.

    Any authenticated role may listen — events carry no sensitive payload, only
    a resource ``kind``/``id``/``status`` so the UI knows which queries to
    refetch.
    """

    async def event_stream():
        pubsub = redis.pubsub()
        await pubsub.subscribe(JOB_EVENTS_CHANNEL)
        try:
            # Initial comment flushes response headers immediately so the
            # client's fetch() resolves and the read loop starts.
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=_HEARTBEAT_SECONDS,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 — degrade to a closed stream, client reconnects
                    logger.warning("job-event stream: pub/sub read failed", exc_info=True)
                    break

                if message is None:
                    # No event within the window — send a keepalive comment.
                    yield ": keepalive\n\n"
                    continue

                data = message.get("data")
                if data is None:
                    continue
                if isinstance(data, bytes):
                    data = data.decode("utf-8", "replace")
                yield f"data: {data}\n\n"
        finally:
            try:
                await pubsub.unsubscribe(JOB_EVENTS_CHANNEL)
                await pubsub.aclose()
            except Exception:  # noqa: BLE001 — teardown is best-effort
                logger.debug("job-event stream: pub/sub teardown failed", exc_info=True)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
