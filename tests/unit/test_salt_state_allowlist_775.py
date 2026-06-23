"""Tests for #775: Salt state name must be validated before being passed to Salt.

Both the live apply (_apply_salt_state) and the dry-run (_apply_salt_state_dry_run)
must reject state names that don't conform to the safe pattern
^[a-zA-Z0-9_][a-zA-Z0-9_./-]{0,199}$.
"""

from __future__ import annotations

import pytest

from fleet_platform.agent.registry import ToolCtx


def _ctx() -> ToolCtx:
    return ToolCtx(actor="op@example.com", role="operator")


# ── Valid state names ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    [
        "base",
        "my_state",
        "foo.bar",
        "states/web/nginx",
        "salt_state-ok",
        "A1_valid",
        "a" * 200,  # max-length boundary
    ],
)
async def test_apply_salt_state_dry_run_accepts_valid_name(name, monkeypatch):
    from fleet_platform.agent import tools as agent_tools

    monkeypatch.setattr(
        "fleet_platform.workers.salt_tasks._run_salt_api",
        lambda *a, **kw: {"status": "ok_test", "result": [{}]},
    )
    result = await agent_tools._apply_salt_state_dry_run(_ctx(), state=name, minion_id="mm7")
    assert result is not None


@pytest.mark.parametrize(
    "name",
    [
        "base",
        "my_state",
        "bootstrap",
        "web/nginx",
        "states.common",
    ],
)
async def test_apply_salt_state_accepts_valid_name(name, monkeypatch):
    from fleet_platform.agent import tools as agent_tools

    monkeypatch.setattr(
        "fleet_platform.workers.salt_tasks._run_salt_api",
        lambda *a, **kw: {"status": "ok", "result": [{}]},
    )
    result = await agent_tools._apply_salt_state(_ctx(), minion_id="mm7", state=name)
    assert result is not None


# ── Invalid state names: dry-run ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad_name",
    [
        "../etc/passwd",  # path traversal
        "/absolute/path",  # starts with /
        "foo;bar",  # shell metachar
        "foo|bar",  # shell metachar
        "state with space",  # spaces not allowed
        "!invalid",  # leading special char
        "a" * 201,  # too long
        "",  # empty
    ],
)
async def test_apply_salt_state_dry_run_rejects_invalid_name(bad_name):
    from fleet_platform.agent import tools as agent_tools

    with pytest.raises(ValueError, match="state name"):
        await agent_tools._apply_salt_state_dry_run(_ctx(), state=bad_name, minion_id="mm7")


@pytest.mark.parametrize(
    "bad_name",
    [
        "../etc/passwd",
        "/absolute/path",
        "foo;rm -rf /",
        "state with space",
        "",
    ],
)
async def test_apply_salt_state_rejects_invalid_name(bad_name):
    from fleet_platform.agent import tools as agent_tools

    with pytest.raises(ValueError, match="state name"):
        await agent_tools._apply_salt_state(_ctx(), minion_id="mm7", state=bad_name)
