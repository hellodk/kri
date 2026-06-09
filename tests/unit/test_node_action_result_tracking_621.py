"""Unit tests for issue #621 — real execution outcome tracking via Celery callback.

Tests:
- _status_from_salt_result: maps run_salt_cmd return values to PendingAction statuses.
- finalize_node_action: updates the DB row correctly for success / failure / missing action.
- Source-contract: node_actions.py uses apply_async + link + status="executing".
"""

import uuid
from unittest.mock import patch

from fleet_platform.workers.salt_tasks import (
    _status_from_salt_result,
    finalize_node_action,
)

# ---------------------------------------------------------------------------
# _status_from_salt_result
# ---------------------------------------------------------------------------


class TestStatusFromSaltResult:
    def test_error_dict_returns_failed(self):
        assert _status_from_salt_result({"status": "error", "reason": "x"}) == "failed"

    def test_normal_salt_return_dict_returns_executed(self):
        assert _status_from_salt_result({"minion1": True}) == "executed"

    def test_empty_dict_returns_executed(self):
        assert _status_from_salt_result({}) == "executed"

    def test_none_returns_executed(self):
        assert _status_from_salt_result(None) == "executed"

    def test_ok_status_dict_returns_executed(self):
        # run_salt_cmd wraps success in {"status": "ok", "result": [...]}
        assert _status_from_salt_result({"status": "ok", "result": [{"minion1": True}]}) == "executed"

    def test_non_dict_returns_executed(self):
        assert _status_from_salt_result("some string") == "executed"
        assert _status_from_salt_result(42) == "executed"


# ---------------------------------------------------------------------------
# finalize_node_action — monkeypatched DB session
# ---------------------------------------------------------------------------


class _FakeAction:
    """Minimal stand-in for a PendingAction ORM row."""

    def __init__(self):
        self.status = "executing"
        self.executed_at = None


class _FakeSession:
    """Minimal sync Session stub."""

    def __init__(self, action):
        self._action = action
        self.committed = False

    def get(self, model, pk):
        return self._action

    def commit(self):
        self.committed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _FakeSessionReturnsNone(_FakeSession):
    def get(self, model, pk):
        return None


class TestFinalizeNodeAction:
    def _action_id(self):
        return str(uuid.uuid4())

    def test_error_result_sets_failed(self):
        fake_action = _FakeAction()
        fake_session = _FakeSession(fake_action)
        aid = self._action_id()
        with patch(
            "fleet_platform.db.session.get_sync_db",
            return_value=fake_session,
        ):
            result = finalize_node_action({"status": "error", "reason": "boom"}, aid)
        assert fake_action.status == "failed"
        assert fake_action.executed_at is not None
        assert fake_session.committed
        assert result == {"status": "failed", "action_id": aid}

    def test_success_result_sets_executed(self):
        fake_action = _FakeAction()
        fake_session = _FakeSession(fake_action)
        aid = self._action_id()
        with patch(
            "fleet_platform.db.session.get_sync_db",
            return_value=fake_session,
        ):
            result = finalize_node_action({"minion1": True}, aid)
        assert fake_action.status == "executed"
        assert fake_action.executed_at is not None
        assert fake_session.committed
        assert result == {"status": "executed", "action_id": aid}

    def test_none_result_sets_executed(self):
        fake_action = _FakeAction()
        fake_session = _FakeSession(fake_action)
        aid = self._action_id()
        with patch(
            "fleet_platform.db.session.get_sync_db",
            return_value=fake_session,
        ):
            result = finalize_node_action(None, aid)
        assert fake_action.status == "executed"
        assert result["status"] == "executed"

    def test_action_not_found_returns_not_found(self):
        fake_session = _FakeSessionReturnsNone(None)
        aid = self._action_id()
        with patch(
            "fleet_platform.db.session.get_sync_db",
            return_value=fake_session,
        ):
            result = finalize_node_action({"status": "error"}, aid)
        assert result == {"status": "not_found", "action_id": aid}


# ---------------------------------------------------------------------------
# Source-contract: node_actions.py must contain the new dispatch idiom
# ---------------------------------------------------------------------------


class TestNodeActionsSourceContract:
    def _read_source(self):
        import pathlib

        src = pathlib.Path(__file__).parent.parent.parent / "fleet_platform" / "api" / "routes" / "node_actions.py"
        return src.read_text()

    def test_apply_async_present(self):
        assert "apply_async" in self._read_source()

    def test_link_finalize_signature_present(self):
        assert "link=finalize_node_action.s(" in self._read_source()

    def test_status_executing_present(self):
        assert 'status = "executing"' in self._read_source()
