"""Unit tests for the executor's dry-run → approval → execute path (#714)."""

from __future__ import annotations

from fleet_platform.agent.executor import (
    AWAITING_APPROVAL,
    DENIED,
    DRY_RUN_REQUIRED,
    OK,
    Executor,
)
from fleet_platform.agent.guards import GuardError
from fleet_platform.agent.registry import ToolCtx, ToolRegistry, ToolSpec


def _schema(props, required):
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


async def _handler(ctx, **kwargs):
    return {"applied": kwargs}


def _registry():
    reg = ToolRegistry()
    reg.register(
        ToolSpec(
            name="apply_salt_state",
            description="x",
            params_schema=_schema(
                {"minion_id": {"type": "string"}, "state": {"type": "string"}}, ["minion_id", "state"]
            ),
            required_role="operator",
            side_effect="write_live",
            requires_approval=True,
            requires_dry_run_first=True,
            handler=_handler,
        )
    )
    return reg


def _ctx(**extra):
    return ToolCtx(actor="op@x.com", role="operator", extra=extra)


async def test_live_tool_requires_dry_run_first():
    ex = Executor(_registry())
    res = await ex.dispatch("apply_salt_state", {"minion_id": "mm9", "state": "s"}, _ctx())
    assert res.status == DRY_RUN_REQUIRED


async def test_live_tool_awaits_approval_after_dry_run():
    ex = Executor(_registry())
    res = await ex.dispatch("apply_salt_state", {"minion_id": "mm9", "state": "s"}, _ctx(dry_run_done=True))
    assert res.status == AWAITING_APPROVAL
    # Crucially, the handler must NOT have executed.
    assert res.result is None


async def test_guard_refusal_denies_before_approval():
    def guard(name, args):
        raise GuardError("nope")

    ex = Executor(_registry(), guard_hook=guard)
    res = await ex.dispatch("apply_salt_state", {"minion_id": "mm9", "state": "s"}, _ctx(dry_run_done=True))
    assert res.status == DENIED
    assert "nope" in (res.error or "")


async def test_dispatch_approved_runs_handler():
    ex = Executor(_registry())
    res = await ex.dispatch_approved("apply_salt_state", {"minion_id": "mm9", "state": "s"}, _ctx())
    assert res.status == OK
    assert res.ok is True
    assert res.result == {"applied": {"minion_id": "mm9", "state": "s"}}


async def test_dispatch_approved_reenforces_guard():
    def guard(name, args):
        raise GuardError("still no")

    ex = Executor(_registry(), guard_hook=guard)
    res = await ex.dispatch_approved("apply_salt_state", {"minion_id": "mm9", "state": "s"}, _ctx())
    assert res.status == DENIED


async def test_dispatch_approved_reenforces_rbac():
    ex = Executor(_registry())
    viewer = ToolCtx(actor="v@x.com", role="viewer")
    res = await ex.dispatch_approved("apply_salt_state", {"minion_id": "mm9", "state": "s"}, viewer)
    assert res.status == DENIED


async def test_dispatch_approved_validates_args():
    ex = Executor(_registry())
    res = await ex.dispatch_approved("apply_salt_state", {"minion_id": "mm9"}, _ctx())
    assert res.status != OK
    assert "state" in (res.error or "")
