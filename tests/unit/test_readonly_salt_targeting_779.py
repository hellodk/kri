"""Tests for #779: read-only Salt tools must reject comma-separated minion targets.

_run_salt_cmd, _apply_salt_state_dry_run, and _ping_node accept a free
minion_id string. If an LLM supplies a comma list (e.g. "mm1,mm2,mm3"),
_run_salt_api silently broadcasts to all of them. These tools must reject any
minion_id containing a comma.
"""

from __future__ import annotations

import json

import pytest

from fleet_platform.agent.registry import ToolCtx


def _ctx() -> ToolCtx:
    return ToolCtx(actor="op@example.com", role="operator", db=object())


async def _fake_get_setting(db, key):
    from fleet_platform.services.platform_settings_svc import SALT_ALLOWED_FUNCTIONS

    if key == SALT_ALLOWED_FUNCTIONS:
        return json.dumps(
            [
                "test.ping",
                "grains.items",
                "grains.get",
                "status.uptime",
                "status.loadavg",
                "disk.usage",
                "service.get_all",
                "service.status",
                "pkg.list_pkgs",
                "network.interfaces",
            ]
        )
    return None


# ── _run_salt_cmd ─────────────────────────────────────────────────────────────


async def test_run_salt_cmd_rejects_comma_minion(monkeypatch):
    from fleet_platform.agent import tools as agent_tools

    monkeypatch.setattr("fleet_platform.services.platform_settings_svc.get_setting", _fake_get_setting)

    with pytest.raises(ValueError, match="single minion"):
        await agent_tools._run_salt_cmd(_ctx(), function="grains.items", minion_id="mm1,mm2,mm3")


async def test_run_salt_cmd_accepts_single_minion(monkeypatch):
    from fleet_platform.agent import tools as agent_tools

    monkeypatch.setattr("fleet_platform.services.platform_settings_svc.get_setting", _fake_get_setting)
    monkeypatch.setattr(
        "fleet_platform.workers.salt_tasks._run_salt_api",
        lambda *a, **kw: {"status": "ok", "result": [{}]},
    )

    result = await agent_tools._run_salt_cmd(_ctx(), function="grains.items", minion_id="mm7")
    assert result is not None


# ── _apply_salt_state_dry_run ─────────────────────────────────────────────────


async def test_dry_run_rejects_comma_minion():
    from fleet_platform.agent import tools as agent_tools

    with pytest.raises(ValueError, match="single minion"):
        await agent_tools._apply_salt_state_dry_run(_ctx(), state="base", minion_id="mm1,mm2")


async def test_dry_run_accepts_single_minion(monkeypatch):
    from fleet_platform.agent import tools as agent_tools

    monkeypatch.setattr(
        "fleet_platform.workers.salt_tasks._run_salt_api",
        lambda *a, **kw: {"status": "ok_test", "result": [{}]},
    )

    result = await agent_tools._apply_salt_state_dry_run(_ctx(), state="base", minion_id="mm7")
    assert result is not None


# ── _ping_node ────────────────────────────────────────────────────────────────


async def test_ping_node_rejects_comma_minion():
    from fleet_platform.agent import tools as agent_tools

    with pytest.raises(ValueError, match="single minion"):
        await agent_tools._ping_node(_ctx(), minion_id="mm1,mm2,mm3")


async def test_ping_node_accepts_single_minion(monkeypatch):
    from fleet_platform.agent import tools as agent_tools

    monkeypatch.setattr(
        "fleet_platform.workers.salt_tasks._run_salt_api",
        lambda *a, **kw: {"status": "ok", "result": [{}]},
    )

    result = await agent_tools._ping_node(_ctx(), minion_id="mm7")
    assert result is not None
