"""Unit tests for the apply-with-approval / co-sign service (#714).

Co-sign state machine and approver-as-actor execution are tested with fakes; the
actual tool execution is stubbed so these stay DB/network-free.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from fleet_platform.services import agent_apply_svc
from fleet_platform.services.agent_apply_svc import ApprovalError


class FakeResult:
    def scalar_one_or_none(self):
        return None  # no Node row — proposal still works with nil node_id


class FakeDB:
    def __init__(self):
        self.added = []
        self.commits = 0

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        pass

    async def execute(self, _q):
        return FakeResult()


class FakeAction:
    """Mimics the PendingAction fields the service touches."""

    def __init__(self, *, co_sign_required=False, status="pending", target_count=1):
        self.status = status
        self.co_sign_required = co_sign_required
        self.target_count = target_count
        self.requested_by = "op@x.com"
        self.tool_name = "apply_salt_state"
        self.action_type = "apply_salt_state"
        self.params = json.dumps({"minion_id": "mm9", "state": "s"})
        self.session_id = None
        self.approved_by = None
        self.approved_at = None
        self.co_signed_by = None
        self.co_signed_at = None
        self.executed_at = None
        self.expires_at = datetime.now(UTC) + timedelta(hours=1)


@pytest.fixture(autouse=True)
def _stub_execute(monkeypatch):
    async def fake_execute(db, action):
        action.status = "executed"
        action.executed_at = datetime.now(UTC)
        return {"status": "executed", "executed_as": action.requested_by}

    monkeypatch.setattr(agent_apply_svc, "_execute", fake_execute)


async def test_create_proposal_sets_cosign_for_many_targets():
    db = FakeDB()
    args = {"minion_id": ",".join(f"mm{i}" for i in range(20, 32)), "state": "s"}  # 12 targets
    action = await agent_apply_svc.create_proposal(
        db, session_id=None, actor="op@x.com", tool_name="apply_salt_state", args=args
    )
    assert action.target_count == 12
    assert action.co_sign_required is True
    assert action.requested_by == "op@x.com"
    assert action.proposed_by_agent is True


async def test_create_proposal_guard_refusal_writes_nothing():
    db = FakeDB()
    with pytest.raises(Exception):
        await agent_apply_svc.create_proposal(
            db,
            session_id=None,
            actor="op@x.com",
            tool_name="restart_service",
            args={"minion_id": "mm9", "service": "sshd"},
        )
    assert db.added == []


async def test_single_approval_executes_when_no_cosign():
    db = FakeDB()
    action = FakeAction(co_sign_required=False)
    out = await agent_apply_svc.approve_proposal(db, action, approver_email="boss@x.com", approver_role="operator")
    assert out["status"] == "executed"
    assert action.approved_by == "boss@x.com"
    assert out["executed_as"] == "op@x.com"  # original operator, not the approver


async def test_cosign_required_waits_then_executes():
    db = FakeDB()
    action = FakeAction(co_sign_required=True, target_count=12)
    first = await agent_apply_svc.approve_proposal(db, action, approver_email="op2@x.com", approver_role="operator")
    assert first["status"] == "awaiting_cosign"
    assert action.status == "awaiting_cosign"
    second = await agent_apply_svc.approve_proposal(db, action, approver_email="admin@x.com", approver_role="admin")
    assert second["status"] == "executed"
    assert action.co_signed_by == "admin@x.com"


async def test_cosign_requires_admin():
    db = FakeDB()
    action = FakeAction(co_sign_required=True, status="awaiting_cosign")
    action.approved_by = "op2@x.com"
    with pytest.raises(ApprovalError, match="admin"):
        await agent_apply_svc.approve_proposal(db, action, approver_email="op3@x.com", approver_role="operator")


async def test_cosign_must_be_different_person():
    db = FakeDB()
    action = FakeAction(co_sign_required=True, status="awaiting_cosign")
    action.approved_by = "admin@x.com"
    with pytest.raises(ApprovalError, match="different person"):
        await agent_apply_svc.approve_proposal(db, action, approver_email="admin@x.com", approver_role="admin")


async def test_cannot_approve_already_executed():
    db = FakeDB()
    action = FakeAction(status="executed")
    with pytest.raises(ApprovalError, match="already"):
        await agent_apply_svc.approve_proposal(db, action, approver_email="x@x.com", approver_role="admin")


async def test_expired_window_rejected():
    db = FakeDB()
    action = FakeAction()
    action.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    with pytest.raises(ApprovalError, match="expired"):
        await agent_apply_svc.approve_proposal(db, action, approver_email="x@x.com", approver_role="operator")
    assert action.status == "expired"


async def test_reject_sets_status():
    db = FakeDB()
    action = FakeAction()
    out = await agent_apply_svc.reject_proposal(db, action, approver_email="x@x.com")
    assert out["status"] == "rejected"
    assert action.status == "rejected"
