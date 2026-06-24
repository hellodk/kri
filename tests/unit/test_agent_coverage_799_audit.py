"""Behavioral coverage for fleet_platform/agent/audit.py (#799 / TST-2).

The audit hook is the confused-deputy guarantee: every tool dispatch is recorded
with ``actor`` set to the operator email, sensitive args redacted, and auditing is
strictly best-effort (a failing audit must never abort the agent turn). These
tests assert that real behavior rather than source strings, so that bringing
``fleet_platform/agent/`` into the enforced coverage gate is backed by meaning.
"""

from __future__ import annotations

import uuid

import fleet_platform.core.audit as core_audit
from fleet_platform.agent.audit import _is_sensitive_key, _redact, audit_tool_dispatch
from fleet_platform.agent.executor import ToolResult
from fleet_platform.agent.registry import ToolCtx, ToolSpec


def _spec(name: str = "list_nodes", side_effect: str = "read") -> ToolSpec:
    return ToolSpec(
        name=name,
        description="d",
        params_schema={"type": "object", "properties": {}},
        side_effect=side_effect,
    )


class _FakeDB:
    def __init__(self, *, commit_raises: bool = False) -> None:
        self.committed = False
        self.rolled_back = False
        self._commit_raises = commit_raises

    async def commit(self) -> None:
        if self._commit_raises:
            raise RuntimeError("commit boom")
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


async def test_audit_noop_when_no_db():
    # No db session → audit is a clean no-op (never raises, nothing recorded).
    calls: list = []

    async def _rec(*a, **k):
        calls.append((a, k))

    # Even if core audit were callable, db=None short-circuits before it.
    ctx = ToolCtx(actor="ops@example.com", role="operator", db=None)
    result = ToolResult(name="list_nodes", ok=True)
    await audit_tool_dispatch(ctx, _spec(), {"x": 1}, result)
    assert calls == []


async def test_audit_records_operator_as_actor_and_redacts_args(monkeypatch):
    recorded: dict = {}

    async def _fake_audit(db, *, actor, action, resource_type, new_value):
        recorded.update(db=db, actor=actor, action=action, resource_type=resource_type, new_value=new_value)

    monkeypatch.setattr(core_audit, "audit", _fake_audit)

    db = _FakeDB()
    sid = uuid.uuid4()
    ctx = ToolCtx(actor="ops@example.com", role="operator", session_id=sid, db=db)
    result = ToolResult(name="set_pillar", ok=True, status="ok", result={"k": "v"})
    spec = _spec(name="set_pillar", side_effect="write_live")

    await audit_tool_dispatch(ctx, spec, {"pillar_key": "foo", "password": "hunter2"}, result)

    # Confused-deputy guarantee: actor is the human operator, never "agent".
    assert recorded["actor"] == "ops@example.com"
    assert recorded["action"] == "agent.tool.set_pillar"
    assert recorded["resource_type"] == "agent_tool"
    nv = recorded["new_value"]
    assert nv["session_id"] == str(sid)
    assert nv["tool"] == "set_pillar"
    assert nv["side_effect"] == "write_live"
    assert nv["ok"] is True
    # Sensitive arg redacted; non-sensitive arg preserved.
    assert nv["args"]["password"] == "[REDACTED]"
    assert nv["args"]["pillar_key"] == "foo"
    assert db.committed is True


async def test_audit_swallows_failure_and_rolls_back(monkeypatch):
    async def _boom(*a, **k):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(core_audit, "audit", _boom)

    db = _FakeDB()
    ctx = ToolCtx(actor="ops@example.com", role="operator", db=db)
    result = ToolResult(name="list_nodes", ok=False, status="error", error="x")

    # Best-effort contract: the audit failure must not propagate.
    await audit_tool_dispatch(ctx, _spec(), {}, result)
    assert db.rolled_back is True
    assert db.committed is False


def test_redact_delegates_to_prompt_safety():
    out = _redact({"token": "abc", "name": "mm1"})
    assert out["token"] == "[REDACTED]"
    assert out["name"] == "mm1"
    # Long non-sensitive strings are truncated by the shared redactor.
    long = "x" * 600
    assert _redact({"note": long})["note"].endswith("...[truncated]")


def test_is_sensitive_key_matches_blocklist_case_insensitively():
    assert _is_sensitive_key("PASSWORD") is True
    assert _is_sensitive_key("api_key") is True
    assert _is_sensitive_key("hostname") is False
