"""Tests for #921: salt_job event publication on ExecutionJob ingest.

Covers:
  * async_publish_job_event helper in job_events.py (shape, best-effort, channel).
  * Source-level assertions that ingest_executions calls async_publish_job_event
    with "salt_job" kind after a successful DB commit.

Run: pytest tests/unit/test_salt_job_events_921.py -q
Do NOT run the full pytest tests/unit/ suite — that is the merge gate.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from fleet_platform.services import job_events

ROOT = Path(__file__).resolve().parents[2]
INGEST_SRC = ROOT / "fleet_platform/api/routes/ingest.py"


# ---------------------------------------------------------------------------
# async_publish_job_event — async variant of the publish helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_publish_sends_salt_job_payload():
    """async_publish_job_event publishes a well-formed salt_job JSON payload."""
    fake_redis = AsyncMock()
    fake_redis.publish = AsyncMock(return_value=1)

    # get_redis is imported lazily inside the function; patch at its source module.
    with patch("fleet_platform.core.redis.get_redis", new=AsyncMock(return_value=fake_redis)):
        n = await job_events.async_publish_job_event("salt_job", "job-uuid-1", "completed", node_id="node-uuid-1")

    assert n == 1
    fake_redis.publish.assert_awaited_once()
    channel, payload = fake_redis.publish.call_args[0]
    assert channel == job_events.JOB_EVENTS_CHANNEL
    decoded = json.loads(payload)
    assert decoded["kind"] == "salt_job"
    assert decoded["id"] == "job-uuid-1"
    assert decoded["status"] == "completed"
    assert decoded["node_id"] == "node-uuid-1"


@pytest.mark.asyncio
async def test_async_publish_swallows_redis_errors():
    """A Redis failure is swallowed and returns 0; it must not raise."""
    fake_redis = AsyncMock()
    fake_redis.publish = AsyncMock(side_effect=RuntimeError("redis down"))

    with patch("fleet_platform.core.redis.get_redis", new=AsyncMock(return_value=fake_redis)):
        result = await job_events.async_publish_job_event("salt_job", "j1", "completed")

    assert result == 0


@pytest.mark.asyncio
async def test_async_publish_drops_none_extras():
    """None-valued extra kwargs must not appear in the published payload."""
    fake_redis = AsyncMock()
    fake_redis.publish = AsyncMock(return_value=0)

    with patch("fleet_platform.core.redis.get_redis", new=AsyncMock(return_value=fake_redis)):
        await job_events.async_publish_job_event("salt_job", "j2", "completed", node_id=None, rc=None)

    _, payload = fake_redis.publish.call_args[0]
    decoded = json.loads(payload)
    assert "node_id" not in decoded
    assert "rc" not in decoded


# ---------------------------------------------------------------------------
# Source inspection: ingest.py imports and calls async_publish_job_event
# ---------------------------------------------------------------------------


def test_ingest_imports_async_publish_job_event():
    """ingest.py must import async_publish_job_event from job_events."""
    src = INGEST_SRC.read_text()
    assert "async_publish_job_event" in src, "ingest.py does not import or reference async_publish_job_event"


def test_ingest_calls_salt_job_kind():
    """ingest.py must call async_publish_job_event with kind='salt_job'."""
    src = INGEST_SRC.read_text()
    assert '"salt_job"' in src or "'salt_job'" in src, (
        "ingest.py does not call async_publish_job_event with kind='salt_job'"
    )


def test_ingest_publish_placed_after_commit():
    """The await call to async_publish_job_event must appear after db.commit() in the
    ingest_executions function body (not in a later unrelated function)."""
    src = INGEST_SRC.read_text()

    # Extract just the ingest_executions function body by slicing between its
    # definition and the next top-level function definition.
    fn_start = src.find("async def ingest_executions(")
    assert fn_start != -1, "Could not locate ingest_executions function"
    # Find the next top-level async def after ingest_executions
    fn_end = src.find("\nasync def ", fn_start + 1)
    if fn_end == -1:
        fn_end = len(src)
    fn_body = src[fn_start:fn_end]

    commit_pos = fn_body.rfind("await db.commit()")
    call_pos = fn_body.find("await async_publish_job_event(")
    assert commit_pos != -1, "Could not find 'await db.commit()' inside ingest_executions"
    assert call_pos != -1, "Could not find 'await async_publish_job_event(' inside ingest_executions"
    assert call_pos > commit_pos, (
        "await async_publish_job_event() must be called AFTER 'await db.commit()' in ingest_executions"
    )
