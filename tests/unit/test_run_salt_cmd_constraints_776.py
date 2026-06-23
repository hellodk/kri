"""Tests for #776: _run_salt_cmd must constrain the LLM-controlled args list.

Constraints required:
  - args list: max 10 items
  - each arg: max 200 characters
  - grains.get / grains.item: first arg must not be a known-sensitive grain key
    (e.g. 'master' or 'pillar' which expose internal Salt configuration)
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
            list(
                [
                    "test.ping",
                    "grains.items",
                    "grains.get",
                    "grains.item",
                    "status.uptime",
                    "status.loadavg",
                    "disk.usage",
                    "service.get_all",
                    "service.status",
                    "pkg.list_pkgs",
                    "network.interfaces",
                ]
            )
        )
    return None


# ── Too many args ─────────────────────────────────────────────────────────────


async def test_run_salt_cmd_rejects_too_many_args(monkeypatch):
    from fleet_platform.agent import tools as agent_tools

    monkeypatch.setattr("fleet_platform.services.platform_settings_svc.get_setting", _fake_get_setting)

    with pytest.raises(ValueError, match="args"):
        await agent_tools._run_salt_cmd(
            _ctx(),
            function="grains.items",
            minion_id="mm7",
            args=["a"] * 11,
        )


async def test_run_salt_cmd_accepts_max_args(monkeypatch):
    """Exactly 10 args should pass the count gate."""
    from fleet_platform.agent import tools as agent_tools

    monkeypatch.setattr("fleet_platform.services.platform_settings_svc.get_setting", _fake_get_setting)
    monkeypatch.setattr(
        "fleet_platform.workers.salt_tasks._run_salt_api",
        lambda *a, **kw: {"status": "ok", "result": [{}]},
    )

    result = await agent_tools._run_salt_cmd(
        _ctx(),
        function="grains.items",
        minion_id="mm7",
        args=["a"] * 10,
    )
    assert result is not None


# ── Arg too long ──────────────────────────────────────────────────────────────


async def test_run_salt_cmd_rejects_arg_too_long(monkeypatch):
    from fleet_platform.agent import tools as agent_tools

    monkeypatch.setattr("fleet_platform.services.platform_settings_svc.get_setting", _fake_get_setting)

    with pytest.raises(ValueError, match="arg"):
        await agent_tools._run_salt_cmd(
            _ctx(),
            function="grains.get",
            minion_id="mm7",
            args=["x" * 201],
        )


async def test_run_salt_cmd_accepts_max_length_arg(monkeypatch):
    from fleet_platform.agent import tools as agent_tools

    monkeypatch.setattr("fleet_platform.services.platform_settings_svc.get_setting", _fake_get_setting)
    monkeypatch.setattr(
        "fleet_platform.workers.salt_tasks._run_salt_api",
        lambda *a, **kw: {"status": "ok", "result": [{}]},
    )

    result = await agent_tools._run_salt_cmd(
        _ctx(),
        function="grains.get",
        minion_id="mm7",
        args=["x" * 200],
    )
    assert result is not None


# ── Sensitive grain key blocklist ─────────────────────────────────────────────


@pytest.mark.parametrize("sensitive_key", ["master", "pillar"])
async def test_run_salt_cmd_blocks_sensitive_grain_key_grains_get(sensitive_key, monkeypatch):
    """grains.get with a sensitive key must be rejected before any Salt call."""
    from fleet_platform.agent import tools as agent_tools

    monkeypatch.setattr("fleet_platform.services.platform_settings_svc.get_setting", _fake_get_setting)

    with pytest.raises(ValueError, match="grain key"):
        await agent_tools._run_salt_cmd(
            _ctx(),
            function="grains.get",
            minion_id="mm7",
            args=[sensitive_key],
        )


@pytest.mark.parametrize("sensitive_key", ["master", "pillar"])
async def test_run_salt_cmd_blocks_sensitive_grain_key_grains_item(sensitive_key, monkeypatch):
    from fleet_platform.agent import tools as agent_tools

    monkeypatch.setattr("fleet_platform.services.platform_settings_svc.get_setting", _fake_get_setting)

    with pytest.raises(ValueError, match="grain key"):
        await agent_tools._run_salt_cmd(
            _ctx(),
            function="grains.item",
            minion_id="mm7",
            args=[sensitive_key],
        )


async def test_run_salt_cmd_allows_safe_grain_key(monkeypatch):
    from fleet_platform.agent import tools as agent_tools

    monkeypatch.setattr("fleet_platform.services.platform_settings_svc.get_setting", _fake_get_setting)
    monkeypatch.setattr(
        "fleet_platform.workers.salt_tasks._run_salt_api",
        lambda *a, **kw: {"status": "ok", "result": [{"os": "Ubuntu"}]},
    )

    result = await agent_tools._run_salt_cmd(
        _ctx(),
        function="grains.get",
        minion_id="mm7",
        args=["os"],
    )
    assert result is not None


# ── Schema reflects constraints ───────────────────────────────────────────────


def test_run_salt_cmd_schema_has_args_constraints():
    """The OpenAI/tool schema for run_salt_cmd must advertise arg limits."""
    from fleet_platform.agent.tools import build_default_registry

    reg = build_default_registry()
    spec = reg.get("run_salt_cmd")
    args_schema = spec.params_schema["properties"]["args"]
    assert "maxItems" in args_schema, "maxItems missing from args schema"
    assert args_schema["maxItems"] <= 10
    items = args_schema.get("items", {})
    assert "maxLength" in items, "items.maxLength missing from args schema"
    assert items["maxLength"] <= 200
