"""Tests for #735 — row-level lock on approve_proposal / reject_proposal (TOCTOU).

Structural test: verify that approve_proposal and reject_proposal each issue a
SELECT ... FOR UPDATE (re-fetch under lock) before mutating state.

Behavioural test: simulate two sequential approvals; the second must see the
already-advanced status and raise ApprovalError.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fleet_platform.services.agent_apply_svc import ApprovalError, approve_proposal, reject_proposal

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_action(status: str = "pending") -> MagicMock:
    action = MagicMock()
    action.id = uuid.uuid4()
    action.status = status
    action.expires_at = datetime.now(UTC) + timedelta(hours=4)
    action.co_sign_required = False
    action.approved_by = None
    action.approved_at = None
    action.co_signed_by = None
    action.co_signed_at = None
    action.params = "{}"
    action.tool_name = "service_stop"
    action.action_type = "service_stop"
    action.requested_by = "operator@example.com"
    action.session_id = None
    return action


class FakeSelectResult:
    """Mimics the result of db.execute(select(...).with_for_update())."""

    def __init__(self, action):
        self._action = action

    def scalar_one_or_none(self):
        return self._action


class _DB:
    """Async-mock DB that records execute calls and tracks with_for_update usage."""

    def __init__(self, locked_action):
        self._locked_action = locked_action
        self.execute_calls: list = []
        self.commit = AsyncMock()
        self.refresh = AsyncMock()
        self.add = MagicMock()

    async def execute(self, stmt):
        self.execute_calls.append(stmt)
        return FakeSelectResult(self._locked_action)


# ---------------------------------------------------------------------------
# #735 structural: approve_proposal must call db.execute with with_for_update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_proposal_issues_with_for_update():
    """approve_proposal must re-fetch the row under a FOR UPDATE lock."""
    action = _make_action("pending")
    locked_action = _make_action("pending")
    locked_action.id = action.id
    locked_action.co_sign_required = False

    db = _DB(locked_action)

    with patch("fleet_platform.services.agent_apply_svc._execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = {"status": "executed", "ok": True}
        await approve_proposal(db, action, approver_email="approver@example.com", approver_role="admin")

    # At least one db.execute call must have been made
    assert db.execute_calls, "approve_proposal must call db.execute to re-fetch the row under lock"

    # The compiled SQL or the statement itself must reference with_for_update.
    # We check by inspecting the statement object — SQLAlchemy attaches
    # _with_for_update (UpdateBase) or the clause has for_update=True.
    found_lock = False
    for stmt in db.execute_calls:
        # SQLAlchemy Select object carries _for_update_arg when with_for_update() was called
        if hasattr(stmt, "_for_update_arg") and stmt._for_update_arg is not None:
            found_lock = True
            break
        # Also accept the string-compilation approach
        try:
            from sqlalchemy.dialects import postgresql

            sql_str = str(stmt.compile(dialect=postgresql.dialect()))
            if "FOR UPDATE" in sql_str.upper():
                found_lock = True
                break
        except Exception:
            pass

    assert found_lock, (
        "approve_proposal must issue a SELECT ... FOR UPDATE before mutating action. "
        "Received execute calls: " + repr([str(s) for s in db.execute_calls])
    )


@pytest.mark.asyncio
async def test_reject_proposal_issues_with_for_update():
    """reject_proposal must re-fetch the row under a FOR UPDATE lock."""
    action = _make_action("pending")
    locked_action = _make_action("pending")
    locked_action.id = action.id

    db = _DB(locked_action)

    await reject_proposal(db, action, approver_email="approver@example.com")

    assert db.execute_calls, "reject_proposal must call db.execute to re-fetch the row under lock"

    found_lock = False
    for stmt in db.execute_calls:
        if hasattr(stmt, "_for_update_arg") and stmt._for_update_arg is not None:
            found_lock = True
            break
        try:
            from sqlalchemy.dialects import postgresql

            sql_str = str(stmt.compile(dialect=postgresql.dialect()))
            if "FOR UPDATE" in sql_str.upper():
                found_lock = True
                break
        except Exception:
            pass

    assert found_lock, (
        "reject_proposal must issue a SELECT ... FOR UPDATE before mutating action. "
        "Received execute calls: " + repr([str(s) for s in db.execute_calls])
    )


# ---------------------------------------------------------------------------
# #735 behavioural: second concurrent approval must be rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_approval_rejected_when_already_approved():
    """Simulate TOCTOU: second approve call sees already-advanced status and must fail."""
    action_first = _make_action("pending")
    action_second = _make_action("pending")
    action_second.id = action_first.id

    # After first approval the status advances to "approved"; the locked re-fetch
    # for the second call must return this already-advanced state.
    already_approved = _make_action("approved")
    already_approved.id = action_first.id

    db_first = _DB(_make_action("pending"))
    db_first._locked_action.id = action_first.id
    db_first._locked_action.co_sign_required = False

    db_second = _DB(already_approved)

    with patch("fleet_platform.services.agent_apply_svc._execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = {"status": "executed", "ok": True}
        # First approval succeeds
        await approve_proposal(db_first, action_first, approver_email="first@example.com", approver_role="admin")

    # Second approval must raise because the locked row is already "approved"
    with pytest.raises(ApprovalError):
        await approve_proposal(db_second, action_second, approver_email="second@example.com", approver_role="admin")


@pytest.mark.asyncio
async def test_second_cosign_approval_rejected_when_already_approved():
    """Same TOCTOU scenario for awaiting_cosign state."""
    action = _make_action("awaiting_cosign")

    already_approved = _make_action("approved")
    already_approved.id = action.id

    db = _DB(already_approved)

    with pytest.raises(ApprovalError):
        await approve_proposal(db, action, approver_email="admin@example.com", approver_role="admin")
