"""Publish half of the live job-event push channel (#756 / ARC-11).

The fleet UI historically learned about job-state changes by running ~40
``refetchInterval`` polling loops across ~20 pages. This module is the
*publish* side of a Redis pub/sub channel that lets the API stream state
transitions to the browser over SSE (see
``fleet_platform/api/routes/events.py``), so those polls can relax to a slow
safety-net interval instead of hammering the API every few seconds.

Celery workers are synchronous, so publishing uses a synchronous Redis client
(the async shared client in ``core.redis`` cannot be driven from the worker's
sync context). The wire format is a single compact JSON object per message.

Publishing is strictly best-effort: a Redis hiccup must never fail or slow
down a running job, so every error is swallowed with a warning. The
frontend's slow poll remains the backstop when an event is dropped.
"""

from __future__ import annotations

import logging
import time
from typing import Any, cast

import redis as sync_redis

from fleet_platform.core.config import settings

logger = logging.getLogger(__name__)

# Channel name shared with the SSE subscriber in api/routes/events.py.
JOB_EVENTS_CHANNEL = "kri:job_events"

_client: sync_redis.Redis | None = None


def _get_client() -> sync_redis.Redis:
    """Lazily build (and cache) a synchronous Redis client for publishing."""
    global _client
    if _client is None:
        _client = sync_redis.Redis.from_url(settings.redis_url)
    return _client


def build_event(kind: str, id: str, status: str, **extra: Any) -> dict[str, Any]:
    """Build the compact, JSON-serialisable event payload.

    Kept as a pure function so the wire shape is unit-testable without a live
    Redis. ``kind`` is the resource family (e.g. ``ansible_job`` or
    ``bootstrap``), ``id`` identifies the affected row, and ``status`` is the
    new state. ``extra`` keys with non-``None`` values are merged in (e.g.
    ``node_id``, ``rc``).
    """
    event: dict[str, Any] = {
        "kind": kind,
        "id": str(id),
        "status": status,
        "ts": time.time(),
    }
    for key, value in extra.items():
        if value is not None:
            event[key] = value
    return event


def publish_job_event(kind: str, id: str, status: str, **extra: Any) -> int:
    """Publish a compact job-state event to the shared Redis channel.

    Best-effort: returns the number of subscribers the message reached (``0``
    when nobody is listening) or ``0`` on any failure. Never raises — a publish
    failure must not break the worker that is reporting progress.
    """
    import json

    try:
        payload = json.dumps(build_event(kind, id, status, **extra), default=str)
        # The synchronous client returns an int, but redis-py's overloaded stubs
        # widen the return type to include Awaitable for the async client.
        return cast(int, _get_client().publish(JOB_EVENTS_CHANNEL, payload))
    except Exception:  # noqa: BLE001 — telemetry must never break the caller
        logger.warning(
            "publish_job_event failed (kind=%s id=%s status=%s)",
            kind,
            id,
            status,
            exc_info=True,
        )
        return 0
