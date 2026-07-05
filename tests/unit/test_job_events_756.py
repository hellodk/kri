"""Tests for #756 (ARC-11): job-event push channel.

Covers the publish helper (``fleet_platform/services/job_events.py``) and the
SSE endpoint registration/contract (``fleet_platform/api/routes/events.py``).

The publish path is strictly best-effort, so the key behaviours are:
  * the wire payload is compact and JSON-serialisable with the right shape,
  * ``None``-valued extras are dropped,
  * a Redis failure is swallowed (returns 0, never raises),
  * the SSE route is registered as a GET that streams ``text/event-stream``.
"""

import json
from unittest.mock import MagicMock, patch

from fleet_platform.services import job_events

# ---------------------------------------------------------------------------
# build_event — pure payload shape
# ---------------------------------------------------------------------------


def test_build_event_basic_shape():
    ev = job_events.build_event("ansible_job", "abc", "running")
    assert ev["kind"] == "ansible_job"
    assert ev["id"] == "abc"
    assert ev["status"] == "running"
    assert isinstance(ev["ts"], float)


def test_build_event_coerces_id_to_str():
    import uuid

    uid = uuid.uuid4()
    ev = job_events.build_event("bootstrap", uid, "completed")
    assert ev["id"] == str(uid)
    assert isinstance(ev["id"], str)


def test_build_event_merges_non_none_extras_and_drops_none():
    ev = job_events.build_event("ansible_job", "j1", "completed", node_id="n1", rc=0, missing=None)
    assert ev["node_id"] == "n1"
    assert ev["rc"] == 0
    assert "missing" not in ev


# ---------------------------------------------------------------------------
# publish_job_event — best-effort publishing
# ---------------------------------------------------------------------------


def test_publish_job_event_publishes_compact_json_to_channel():
    fake = MagicMock()
    fake.publish.return_value = 2
    with patch.object(job_events, "_get_client", return_value=fake):
        n = job_events.publish_job_event("ansible_job", "j1", "running", node_id="n1")
    assert n == 2
    fake.publish.assert_called_once()
    channel, payload = fake.publish.call_args[0]
    assert channel == job_events.JOB_EVENTS_CHANNEL
    decoded = json.loads(payload)
    assert decoded["kind"] == "ansible_job"
    assert decoded["id"] == "j1"
    assert decoded["status"] == "running"
    assert decoded["node_id"] == "n1"


def test_publish_job_event_swallows_redis_errors():
    fake = MagicMock()
    fake.publish.side_effect = RuntimeError("redis down")
    with patch.object(job_events, "_get_client", return_value=fake):
        # Must not raise, and reports 0 deliveries.
        assert job_events.publish_job_event("bootstrap", "n1", "failed") == 0


def test_channel_name_is_stable():
    # The frontend/SSE subscriber relies on this exact channel name.
    assert job_events.JOB_EVENTS_CHANNEL == "kri:job_events"


# ---------------------------------------------------------------------------
# SSE endpoint — registration / contract
# ---------------------------------------------------------------------------


def test_events_router_exposes_job_stream_get():
    from fleet_platform.api.routes import events

    paths = {(r.path, tuple(sorted(r.methods))) for r in events.router.routes}  # type: ignore[attr-defined]
    assert ("/api/v1/events/jobs/stream", ("GET",)) in paths


def test_events_router_registered_in_app():
    from fleet_platform.api.main import create_app

    app = create_app()
    paths = set(app.openapi()["paths"])
    assert "/api/v1/events/jobs/stream" in paths
