"""Unit tests for #640 — finalize_node_action queue fix + reap_stuck_pending_actions.

Tests are purely behavioral:
- The queue= attribute on finalize_node_action is asserted directly (this is the
  test that would have caught the original bug — wrong queue → task never consumed).
- The noop guard in finalize_node_action is exercised with fake DB sessions.
- The reaper task logic is exercised with fake DB sessions; no real DB or broker.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Fix 1: finalize_node_action must be routed to a consumed queue
# ---------------------------------------------------------------------------


def test_finalize_node_action_queue_is_maintenance():
    """Regression guard: the task must carry queue='maintenance' so the worker
    (--queues default,maintenance,...) actually picks it up.  Before #640 this
    attribute was absent → routed to the default 'celery' queue → never consumed."""
    from fleet_platform.workers.salt_tasks import finalize_node_action

    assert finalize_node_action.queue == "maintenance", (
        f"finalize_node_action.queue = {finalize_node_action.queue!r}; "
        "expected 'maintenance' — task will never be consumed without it"
    )


# ---------------------------------------------------------------------------
# Helpers for fake DB sessions
# ---------------------------------------------------------------------------


def _make_fake_action(status: str) -> MagicMock:
    action = MagicMock()
    action.status = status
    action.executed_at = None
    return action


# ---------------------------------------------------------------------------
# Fix 1 continued: noop guard — do not clobber a non-executing status
# ---------------------------------------------------------------------------


def _patch_sync_db(fake_action_or_none):
    """Return a patch context for fleet_platform.db.session.get_sync_db that yields
    a fake session whose .get() returns *fake_action_or_none*."""
    fake_db = MagicMock()
    fake_db.get.return_value = fake_action_or_none
    fake_db.execute.return_value.rowcount = 0

    # get_sync_db is used as `with get_sync_db() as db:` inside the task body.
    # The task imports it locally, so we must patch the canonical location.
    mock_cm = MagicMock()
    mock_cm.__enter__ = MagicMock(return_value=fake_db)
    mock_cm.__exit__ = MagicMock(return_value=False)

    mock_factory = MagicMock(return_value=mock_cm)
    return patch("fleet_platform.db.session.get_sync_db", mock_factory), fake_db


def test_finalize_node_action_noop_when_status_not_executing():
    """If the action is no longer 'executing' (e.g. reaped to 'failed') the
    callback must return noop and leave status untouched."""
    from fleet_platform.workers.salt_tasks import finalize_node_action

    action_id = str(uuid.uuid4())
    fake_action = _make_fake_action("rejected")
    patcher, _ = _patch_sync_db(fake_action)

    with patcher:
        result = finalize_node_action({"status": "ok"}, action_id)

    assert result["status"] == "noop"
    assert result["action_id"] == action_id
    # Status must not have been mutated
    assert fake_action.status == "rejected"


def test_finalize_node_action_updates_when_executing():
    """When the action IS 'executing', the callback must flip status and set executed_at."""
    from fleet_platform.workers.salt_tasks import finalize_node_action

    action_id = str(uuid.uuid4())
    fake_action = _make_fake_action("executing")
    patcher, _ = _patch_sync_db(fake_action)

    with patcher:
        result = finalize_node_action({"status": "ok"}, action_id)

    # Salt returned a non-error dict → status should be "executed"
    assert result["status"] == "executed"
    assert result["action_id"] == action_id
    assert fake_action.status == "executed"
    assert fake_action.executed_at is not None


def test_finalize_node_action_not_found():
    """When the action row does not exist the callback must return not_found."""
    from fleet_platform.workers.salt_tasks import finalize_node_action

    action_id = str(uuid.uuid4())
    patcher, _ = _patch_sync_db(None)

    with patcher:
        result = finalize_node_action({"status": "ok"}, action_id)

    assert result["status"] == "not_found"
    assert result["action_id"] == action_id


# ---------------------------------------------------------------------------
# Fix 2: reap_stuck_pending_actions — behavioral tests with fake DB
# ---------------------------------------------------------------------------


def _make_update_result(rowcount: int) -> MagicMock:
    r = MagicMock()
    r.rowcount = rowcount
    return r


def test_reap_stuck_pending_actions_task_is_on_maintenance_queue():
    """The reaper task must carry queue='maintenance' so it is actually consumed."""
    from fleet_platform.workers.maintenance import reap_stuck_pending_actions

    assert reap_stuck_pending_actions.queue == "maintenance"


def test_reap_stuck_pending_actions_flips_statuses():
    """The reaper must:
    - issue an UPDATE for 'executing' rows older than 10 min → 'failed'
    - issue an UPDATE for 'pending' rows past expires_at → 'expired'
    - call db.commit()
    - return the correct row counts
    """
    from fleet_platform.workers.maintenance import reap_stuck_pending_actions

    executing_result = _make_update_result(1)
    expired_result = _make_update_result(2)

    # db.execute() will be called twice (once per UPDATE); return results in order
    fake_db = MagicMock()
    fake_db.execute.side_effect = [executing_result, expired_result]

    with patch("fleet_platform.workers.maintenance.get_sync_db") as mock_get_db:
        mock_get_db.return_value.__enter__ = lambda s: fake_db
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        result = reap_stuck_pending_actions()

    assert result == {"reaped_executing": 1, "expired_pending": 2}
    # Commit must have been called exactly once
    fake_db.commit.assert_called_once()
    # execute must have been called exactly twice (one UPDATE per status class)
    assert fake_db.execute.call_count == 2


def test_reap_stuck_pending_actions_returns_zeros_when_nothing_to_reap():
    """When no rows match, the reaper must return zeros — not raise."""
    from fleet_platform.workers.maintenance import reap_stuck_pending_actions

    fake_db = MagicMock()
    fake_db.execute.side_effect = [_make_update_result(0), _make_update_result(0)]

    with patch("fleet_platform.workers.maintenance.get_sync_db") as mock_get_db:
        mock_get_db.return_value.__enter__ = lambda s: fake_db
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        result = reap_stuck_pending_actions()

    assert result == {"reaped_executing": 0, "expired_pending": 0}
    fake_db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Fix 3: beat schedule includes the new reaper
# ---------------------------------------------------------------------------


def test_beat_schedule_contains_reap_stuck_pending_actions():
    """The beat schedule must have an entry for the new reaper task so it runs
    automatically without a manual celery call."""
    from fleet_platform.workers.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    assert "reap-stuck-pending-actions" in schedule, (
        "beat_schedule is missing 'reap-stuck-pending-actions' — the reaper will never run automatically"
    )
    entry = schedule["reap-stuck-pending-actions"]
    assert entry["task"] == "fleet_platform.workers.maintenance.reap_stuck_pending_actions"
    assert entry.get("options", {}).get("queue") == "maintenance"
