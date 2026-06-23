"""#711 Phase B — executor dispatch: RBAC, validation, gates, idempotency, audit."""

import uuid

from fleet_platform.agent.executor import (
    AWAITING_APPROVAL,
    DENIED,
    DRY_RUN_REQUIRED,
    ERROR,
    OK,
    Executor,
    validate_args,
)
from fleet_platform.agent.registry import ToolCtx, ToolRegistry, ToolSpec

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "node_id": {"type": "string", "maxLength": 64},
        "count": {"type": "integer", "minimum": 1, "maximum": 10},
        "mode": {"type": "string", "enum": ["a", "b"]},
    },
    "required": ["node_id"],
}


# --- validate_args -----------------------------------------------------------


def test_validate_ok():
    assert validate_args(SCHEMA, {"node_id": "n1", "count": 3, "mode": "a"}) is None


def test_validate_missing_required():
    assert "missing required" in validate_args(SCHEMA, {"count": 3})


def test_validate_additional_properties_rejected():
    assert "unexpected" in validate_args(SCHEMA, {"node_id": "n", "bogus": 1})


def test_validate_type_mismatch():
    assert "must be integer" in validate_args(SCHEMA, {"node_id": "n", "count": "x"})


def test_validate_bool_is_not_integer():
    assert validate_args(SCHEMA, {"node_id": "n", "count": True}) is not None


def test_validate_enum():
    assert "one of" in validate_args(SCHEMA, {"node_id": "n", "mode": "z"})


def test_validate_maxlength_and_bounds():
    assert "maxLength" in validate_args(SCHEMA, {"node_id": "x" * 65})
    assert "maximum" in validate_args(SCHEMA, {"node_id": "n", "count": 99})
    assert "minimum" in validate_args(SCHEMA, {"node_id": "n", "count": 0})


# --- dispatch helpers --------------------------------------------------------


def _ctx(role="operator", **extra):
    return ToolCtx(actor="alice@org", role=role, session_id=uuid.uuid4(), extra=extra)


def _registry(handler, *, role="viewer", requires_approval=False, requires_dry_run_first=False, enabled=True):
    r = ToolRegistry()
    r.register(
        ToolSpec(
            name="get_node",
            description="d",
            params_schema=SCHEMA,
            required_role=role,
            side_effect="read",
            requires_approval=requires_approval,
            requires_dry_run_first=requires_dry_run_first,
            enabled=enabled,
            handler=handler,
        )
    )
    return r


async def _echo(ctx, **kwargs):
    return {"echo": kwargs, "actor": ctx.actor}


# --- dispatch ----------------------------------------------------------------


async def test_dispatch_success_and_audits():
    audited = []

    async def hook(ctx, spec, args, result):
        audited.append((ctx.actor, spec.name, result.ok))

    ex = Executor(_registry(_echo), audit_hook=hook)
    res = await ex.dispatch("get_node", {"node_id": "n1"}, _ctx())
    assert res.ok and res.status == OK
    assert res.result["actor"] == "alice@org"
    assert audited == [("alice@org", "get_node", True)]


async def test_dispatch_unknown_tool_denied():
    ex = Executor(_registry(_echo))
    res = await ex.dispatch("nope", {}, _ctx())
    assert res.status == DENIED


async def test_dispatch_disabled_tool_denied():
    ex = Executor(_registry(_echo, enabled=False))
    res = await ex.dispatch("get_node", {"node_id": "n"}, _ctx())
    assert res.status == DENIED


async def test_dispatch_role_recheck_denies_low_role():
    ex = Executor(_registry(_echo, role="admin"))
    res = await ex.dispatch("get_node", {"node_id": "n"}, _ctx(role="operator"))
    assert res.status == DENIED
    assert "cannot call" in res.error


async def test_dispatch_invalid_args_error():
    ex = Executor(_registry(_echo))
    res = await ex.dispatch("get_node", {"bogus": 1}, _ctx())
    assert res.status == ERROR


async def test_dispatch_approval_gated_does_not_execute():
    calls = []

    async def handler(ctx, **kw):
        calls.append(kw)
        return "ran"

    ex = Executor(_registry(handler, requires_approval=True))
    res = await ex.dispatch("get_node", {"node_id": "n"}, _ctx())
    assert res.status == AWAITING_APPROVAL
    assert calls == [], "approval-gated tool must not execute in the executor"


async def test_dispatch_dry_run_required_then_allowed():
    ex = Executor(_registry(_echo, requires_dry_run_first=True))
    blocked = await ex.dispatch("get_node", {"node_id": "n"}, _ctx())
    assert blocked.status == DRY_RUN_REQUIRED
    allowed = await ex.dispatch("get_node", {"node_id": "n"}, _ctx(dry_run_done=True))
    assert allowed.status == OK


async def test_dispatch_idempotency_caches_within_session():
    calls = []

    async def handler(ctx, **kw):
        calls.append(kw)
        return len(calls)

    ex = Executor(_registry(handler))
    ctx = _ctx()
    r1 = await ex.dispatch("get_node", {"node_id": "n"}, ctx)
    r2 = await ex.dispatch("get_node", {"node_id": "n"}, ctx)
    assert r1.result == 1
    assert r2.cached is True and r2.result == 1
    assert len(calls) == 1, "handler should run once; second call served from cache"


async def test_dispatch_handler_exception_becomes_error_result():
    async def boom(ctx, **kw):
        raise RuntimeError("kaboom")

    ex = Executor(_registry(boom))
    res = await ex.dispatch("get_node", {"node_id": "n"}, _ctx())
    assert res.status == ERROR and "kaboom" in res.error


async def test_dispatch_missing_handler_errors():
    r = ToolRegistry()
    r.register(ToolSpec(name="get_node", description="d", params_schema=SCHEMA, required_role="viewer"))
    ex = Executor(r)
    res = await ex.dispatch("get_node", {"node_id": "n"}, _ctx())
    assert res.status == ERROR and "no handler" in res.error
