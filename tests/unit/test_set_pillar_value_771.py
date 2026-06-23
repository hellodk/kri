"""Tests for #771: _set_pillar must validate its value arg and actually apply it.

The old implementation only called saltutil.refresh_pillar and silently discarded
the value argument. The fix must:
  1. Raise ValueError for a missing/empty/blank value.
  2. Raise ValueError for a missing/empty pillar_key.
  3. Actually call pillar.set on the minion before the refresh.
"""

from __future__ import annotations

import pytest

from fleet_platform.agent.registry import ToolCtx


def _ctx() -> ToolCtx:
    return ToolCtx(actor="op@example.com", role="operator")


# ── Validation: empty / blank value ──────────────────────────────────────────


async def test_set_pillar_rejects_empty_value():
    from fleet_platform.agent.tools import _set_pillar

    with pytest.raises(ValueError, match="value"):
        await _set_pillar(_ctx(), minion_id="mm7", pillar_key="my_key", value="")


async def test_set_pillar_rejects_blank_value():
    from fleet_platform.agent.tools import _set_pillar

    with pytest.raises(ValueError, match="value"):
        await _set_pillar(_ctx(), minion_id="mm7", pillar_key="my_key", value="   ")


async def test_set_pillar_rejects_empty_pillar_key():
    from fleet_platform.agent.tools import _set_pillar

    with pytest.raises(ValueError, match="pillar_key"):
        await _set_pillar(_ctx(), minion_id="mm7", pillar_key="", value="some_value")


async def test_set_pillar_rejects_blank_pillar_key():
    from fleet_platform.agent.tools import _set_pillar

    with pytest.raises(ValueError, match="pillar_key"):
        await _set_pillar(_ctx(), minion_id="mm7", pillar_key="  ", value="some_value")


# ── Actual application: pillar.set must be called ────────────────────────────


async def test_set_pillar_calls_pillar_set(monkeypatch):
    """Valid args must invoke pillar.set before saltutil.refresh_pillar."""
    from fleet_platform.agent import tools as agent_tools

    calls: list[tuple] = []

    def _fake_run_salt_api(function, target, args=None, kwarg=None, timeout=60):
        calls.append((function, target, args))
        return {"status": "ok", "result": [{}]}

    monkeypatch.setattr(
        "fleet_platform.workers.salt_tasks._run_salt_api",
        _fake_run_salt_api,
    )

    await agent_tools._set_pillar(_ctx(), minion_id="mm7", pillar_key="app_secret", value="s3cr3t")

    functions_called = [c[0] for c in calls]
    assert "pillar.set" in functions_called, "pillar.set was not called"
    assert "saltutil.refresh_pillar" in functions_called, "saltutil.refresh_pillar was not called"

    pillar_set_call = next(c for c in calls if c[0] == "pillar.set")
    assert pillar_set_call[1] == "mm7"
    assert "app_secret" in (pillar_set_call[2] or [])
    assert "s3cr3t" in (pillar_set_call[2] or [])


async def test_set_pillar_returns_key_and_value(monkeypatch):
    """Return dict must echo back pillar_key and value for audit trail."""
    from fleet_platform.agent import tools as agent_tools

    monkeypatch.setattr(
        "fleet_platform.workers.salt_tasks._run_salt_api",
        lambda *a, **kw: {"status": "ok", "result": [{}]},
    )

    result = await agent_tools._set_pillar(_ctx(), minion_id="mm7", pillar_key="db_pass", value="hunter2")

    assert result["pillar_key"] == "db_pass"
    assert result["value"] == "hunter2"
    assert "set_result" in result
    assert "refreshed" in result
