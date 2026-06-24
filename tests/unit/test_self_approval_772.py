"""Unit tests for #772 — operators must not self-approve their own proposals.

An operator who requested (or triggered) an agent-proposed action must not be
able to approve it themselves.  The approver must always differ from the
requester, regardless of whether the action was proposed by an agent or by a
human operator.
"""

from __future__ import annotations

import json
import uuid

import pytest

from fleet_platform.services.agent_apply_svc import ApprovalError


class FakeResult:
    def __init__(self, value=None):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class FakeDB:
    def __init__(self, locked_action=None):
        self.locked_action = locked_action
        self.commits = 0

    def add(self, obj):
        pass

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        pass

    async def execute(self, _q):
        return FakeResult(self.locked_action)


class FakeAction:
    """Minimal PendingAction stand-in."""

    def __init__(
        self,
        *,
        co_sign_required: bool = False,
        status: str = "pending",
        proposed_by_agent: bool = True,
        requested_by: str = "op@example.com",
    ):
        self.id = uuid.uuid4()
        self.status = status
        self.co_sign_required = co_sign_required
        self.proposed_by_agent = proposed_by_agent
        self.requested_by = requested_by
        self.tool_name = "apply_salt_state"
        self.action_type = "apply_salt_state"
        self.params = json.dumps({"minion_id": "mm1", "state": "test"})
        self.session_id = None
        self.approved_by = None
        self.approved_at = None
        self.co_signed_by = None
        self.co_signed_at = None
        self.expires_at = None
        self.target_count = 1


# ---------------------------------------------------------------------------
# Self-approval blocked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_self_approval_blocked_for_agent_proposed_action():
    """The requester must not be able to approve their own agent-proposed action."""
    action = FakeAction(proposed_by_agent=True, requested_by="op@example.com")
    db = FakeDB(locked_action=action)

    with pytest.raises(ApprovalError, match="approver must differ"):
        from fleet_platform.services import agent_apply_svc

        await agent_apply_svc.approve_proposal(
            db,
            action,
            approver_email="op@example.com",
            approver_role="operator",
        )


@pytest.mark.asyncio
async def test_self_approval_blocked_for_human_proposed_action():
    """Self-approval is prohibited regardless of whether the action was agent-proposed."""
    action = FakeAction(proposed_by_agent=False, requested_by="op@example.com")
    db = FakeDB(locked_action=action)

    with pytest.raises(ApprovalError, match="approver must differ"):
        from fleet_platform.services import agent_apply_svc

        await agent_apply_svc.approve_proposal(
            db,
            action,
            approver_email="op@example.com",
            approver_role="operator",
        )


# ---------------------------------------------------------------------------
# Legitimate approval (different approver) still works
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_different_approver_is_allowed(monkeypatch):
    """A second operator who is not the requester can approve without co-sign."""
    action = FakeAction(
        proposed_by_agent=True,
        requested_by="op@example.com",
        co_sign_required=False,
    )
    db = FakeDB(locked_action=action)

    # Stub out the execute path so we don't need real DB/Celery
    from fleet_platform.services import agent_apply_svc

    async def _fake_execute(db, action):
        return {"status": "executed"}

    monkeypatch.setattr(agent_apply_svc, "_execute", _fake_execute)

    result = await agent_apply_svc.approve_proposal(
        db,
        action,
        approver_email="admin@example.com",
        approver_role="admin",
    )
    assert result["status"] == "executed"


@pytest.mark.asyncio
async def test_cosign_self_approval_still_blocked():
    """Existing co-sign guard: first approver cannot also be the co-signer."""
    action = FakeAction(
        proposed_by_agent=True,
        requested_by="op@example.com",
        co_sign_required=True,
        status="awaiting_cosign",
    )
    action.approved_by = "first_admin@example.com"
    db = FakeDB(locked_action=action)

    with pytest.raises(ApprovalError, match="different person"):
        from fleet_platform.services import agent_apply_svc

        await agent_apply_svc.approve_proposal(
            db,
            action,
            approver_email="first_admin@example.com",
            approver_role="admin",
        )
