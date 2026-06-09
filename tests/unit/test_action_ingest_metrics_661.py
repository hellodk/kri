# tests/unit/test_action_ingest_metrics_661.py
"""Behavioral tests for the node-action / ingest / salt-dispatch Prometheus metrics
added in issue #661 (audit #639 observability).

Run: pytest tests/unit/test_action_ingest_metrics_661.py -q
Do NOT run the full pytest tests/unit/ suite — that is the merge gate.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch  # noqa: F401

# ---------------------------------------------------------------------------
# 1. Metric registration — names and label keys
# ---------------------------------------------------------------------------


def test_node_action_total_name_and_labels():
    from fleet_platform.metrics import node_action_total

    # prometheus_client strips _total from ._name; _original_name holds the full canonical name
    assert node_action_total._original_name == "kri_node_action_total"
    assert set(node_action_total._labelnames) == {"action_type", "status"}


def test_pending_action_queue_depth_name_and_no_labels():
    from fleet_platform.metrics import pending_action_queue_depth

    assert pending_action_queue_depth._name == "kri_pending_action_queue_depth"
    assert list(pending_action_queue_depth._labelnames) == []


def test_process_stats_rows_ingested_total_name():
    from fleet_platform.metrics import process_stats_rows_ingested_total

    assert process_stats_rows_ingested_total._original_name == "kri_process_stats_rows_ingested_total"
    assert list(process_stats_rows_ingested_total._labelnames) == []


def test_process_stats_rows_dropped_total_name():
    from fleet_platform.metrics import process_stats_rows_dropped_total

    assert process_stats_rows_dropped_total._original_name == "kri_process_stats_rows_dropped_total"
    assert list(process_stats_rows_dropped_total._labelnames) == []


def test_salt_dispatch_total_name_and_labels():
    from fleet_platform.metrics import salt_dispatch_total

    assert salt_dispatch_total._original_name == "kri_salt_dispatch_total"
    assert set(salt_dispatch_total._labelnames) == {"function", "outcome"}


# ---------------------------------------------------------------------------
# 2. Counter / Gauge increment behaviour
# ---------------------------------------------------------------------------


def test_node_action_total_increment():
    from fleet_platform.metrics import node_action_total

    label = node_action_total.labels(action_type="process_stop", status="executed")
    before = label._value.get()
    label.inc()
    assert label._value.get() == before + 1.0


def test_process_stats_rows_ingested_total_increment():
    from fleet_platform.metrics import process_stats_rows_ingested_total

    before = process_stats_rows_ingested_total._value.get()
    process_stats_rows_ingested_total.inc(5)
    assert process_stats_rows_ingested_total._value.get() == before + 5.0


def test_pending_action_queue_depth_set():
    from fleet_platform.metrics import pending_action_queue_depth

    pending_action_queue_depth.set(5)
    # Collect the sample to verify the exposed value
    samples = list(pending_action_queue_depth.collect())
    assert len(samples) == 1
    gauge_val = samples[0].samples[0].value
    assert gauge_val == 5.0


# ---------------------------------------------------------------------------
# 3. refresh_pending_action_queue_depth_gauge — monkeypatched DB
# ---------------------------------------------------------------------------


def test_refresh_pending_action_queue_depth_gauge_sets_value():
    """Monkeypatch get_sync_db to return a fake session yielding count=7."""
    from fleet_platform.metrics import pending_action_queue_depth

    fake_scalar = MagicMock()
    fake_scalar.scalar_one.return_value = 7

    fake_execute = MagicMock(return_value=fake_scalar)

    fake_db = MagicMock()
    fake_db.execute = fake_execute

    @contextmanager
    def fake_get_sync_db():
        yield fake_db

    with patch("fleet_platform.db.session.get_sync_db", fake_get_sync_db):
        from fleet_platform.api.metrics_collectors import refresh_pending_action_queue_depth_gauge

        refresh_pending_action_queue_depth_gauge()

    samples = list(pending_action_queue_depth.collect())
    gauge_val = samples[0].samples[0].value
    assert gauge_val == 7.0


def test_refresh_pending_action_queue_depth_gauge_swallows_errors():
    """Errors must not propagate — /metrics must never 500."""
    with patch("fleet_platform.db.session.get_sync_db", side_effect=RuntimeError("DB down")):
        from fleet_platform.api.metrics_collectors import refresh_pending_action_queue_depth_gauge

        # Should not raise
        refresh_pending_action_queue_depth_gauge()


# ---------------------------------------------------------------------------
# 4. Source-contract: instrumentation calls exist in the right modules
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (_ROOT / relative).read_text()


def test_node_actions_references_node_action_total():
    src = _read("fleet_platform/api/routes/node_actions.py")
    assert "node_action_total.labels(" in src, "node_actions.py must call node_action_total.labels("


def test_ingest_references_process_stats_ingested():
    src = _read("fleet_platform/api/routes/ingest.py")
    assert "process_stats_rows_ingested_total" in src, "ingest.py must reference process_stats_rows_ingested_total"


def test_salt_tasks_references_salt_dispatch_total():
    src = _read("fleet_platform/workers/salt_tasks.py")
    assert "salt_dispatch_total.labels(" in src, "salt_tasks.py must call salt_dispatch_total.labels("


def test_node_actions_references_rejected():
    src = _read("fleet_platform/api/routes/node_actions.py")
    assert 'status="rejected"' in src, "node_actions.py must increment rejected status"


def test_salt_tasks_references_node_action_total():
    src = _read("fleet_platform/workers/salt_tasks.py")
    assert "node_action_total.labels(" in src, "salt_tasks.py must call node_action_total.labels( for finalize"
