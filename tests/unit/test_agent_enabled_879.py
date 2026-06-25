"""Unit tests for issue #879 — AGENT_ENABLED master kill-switch.

Coverage:
- ``is_agent_enabled`` accessor: env override wins, DB row honoured, default OFF.
- ``require_agent_enabled`` dependency: raises 403 when off, passes when on.
- The gate is wired onto every *mutating* agent route (run/stream, approve,
  reject, promote) and NOT onto the read-only GETs.
- ``GET /status`` endpoint returns ``{"enabled": <bool>}`` reflecting the switch.

These follow the direct-call + mocked-DB style used by other route unit tests
(see tests/unit/test_provision_status_endpoint_558.py): the endpoint and
dependency callables are invoked directly with an AsyncMock DB and the setting
accessor patched, so no live database is required.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# 1. is_agent_enabled accessor
# ---------------------------------------------------------------------------


class TestIsAgentEnabledAccessor:
    def _call(self, setting_value):
        """Run is_agent_enabled with get_setting mocked to return setting_value."""
        from fleet_platform.services import platform_settings_svc as svc

        db = AsyncMock()
        with patch.object(svc, "get_setting", new=AsyncMock(return_value=setting_value)):
            return asyncio.run(svc.is_agent_enabled(db))

    def test_defaults_to_disabled_when_unset(self, monkeypatch):
        """No env var and no DB row → disabled (the kill-switch default)."""
        monkeypatch.delenv("AGENT_ENABLED", raising=False)
        assert self._call(None) is False

    def test_db_true_enables(self, monkeypatch):
        monkeypatch.delenv("AGENT_ENABLED", raising=False)
        assert self._call("true") is True

    def test_db_false_disables(self, monkeypatch):
        monkeypatch.delenv("AGENT_ENABLED", raising=False)
        assert self._call("false") is False

    def test_unrecognised_db_value_is_disabled(self, monkeypatch):
        monkeypatch.delenv("AGENT_ENABLED", raising=False)
        assert self._call("maybe") is False

    @pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on"])
    def test_env_override_enables(self, monkeypatch, raw):
        """An explicit truthy env var enables even when the DB row is off."""
        monkeypatch.setenv("AGENT_ENABLED", raw)
        assert self._call("false") is True

    @pytest.mark.parametrize("raw", ["0", "false", "no", "off"])
    def test_env_override_disables(self, monkeypatch, raw):
        """An explicit falsy env var disables even when the DB row is on."""
        monkeypatch.setenv("AGENT_ENABLED", raw)
        assert self._call("true") is False


# ---------------------------------------------------------------------------
# 2. require_agent_enabled dependency
# ---------------------------------------------------------------------------


class TestRequireAgentEnabledDependency:
    def test_raises_403_when_disabled(self):
        from fleet_platform.api.routes import agent

        db = AsyncMock()
        with patch.object(agent, "is_agent_enabled", new=AsyncMock(return_value=False)):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(agent.require_agent_enabled(db=db))
        assert exc_info.value.status_code == 403
        assert "disabled" in exc_info.value.detail.lower()
        assert "AGENT_ENABLED" in exc_info.value.detail

    def test_passes_when_enabled(self):
        from fleet_platform.api.routes import agent

        db = AsyncMock()
        with patch.object(agent, "is_agent_enabled", new=AsyncMock(return_value=True)):
            result = asyncio.run(agent.require_agent_enabled(db=db))
        assert result is None


# ---------------------------------------------------------------------------
# 3. Route wiring — gate applied to mutating endpoints only
# ---------------------------------------------------------------------------


def _dependency_calls(route):
    """Collect every dependency callable in a route's dependant tree."""
    calls = []

    def walk(dep):
        for sub in dep.dependencies:
            calls.append(sub.call)
            walk(sub)

    walk(route.dependant)
    return calls


def _find_route(method: str, path: str):
    from fleet_platform.api.routes.agent import router

    for r in router.routes:
        if getattr(r, "path", None) == path and method in getattr(r, "methods", set()):
            return r
    raise AssertionError(f"route not found: {method} {path}")


MUTATING_ROUTES = [
    ("POST", "/api/v1/agent/run/stream"),
    ("POST", "/api/v1/agent/actions/{action_id}/approve"),
    ("POST", "/api/v1/agent/actions/{action_id}/reject"),
    ("POST", "/api/v1/agent/artifacts/{session_id}/{filename}/promote"),
]

READONLY_ROUTES = [
    ("GET", "/api/v1/agent/artifacts"),
    ("GET", "/api/v1/agent/sessions"),
    ("GET", "/api/v1/agent/tiers"),
    ("GET", "/api/v1/agent/costs"),
    ("GET", "/api/v1/agent/actions"),
    ("GET", "/api/v1/agent/status"),
]


class TestGateWiring:
    @pytest.mark.parametrize("method,path", MUTATING_ROUTES)
    def test_mutating_routes_have_gate(self, method, path):
        from fleet_platform.api.routes.agent import require_agent_enabled

        route = _find_route(method, path)
        assert require_agent_enabled in _dependency_calls(route), (
            f"{method} {path} must depend on require_agent_enabled (the kill-switch gate)"
        )

    @pytest.mark.parametrize("method,path", READONLY_ROUTES)
    def test_readonly_routes_have_no_gate(self, method, path):
        from fleet_platform.api.routes.agent import require_agent_enabled

        route = _find_route(method, path)
        assert require_agent_enabled not in _dependency_calls(route), (
            f"{method} {path} is read-only and must NOT be gated by the kill-switch"
        )


# ---------------------------------------------------------------------------
# 4. /status endpoint reflects the setting
# ---------------------------------------------------------------------------


class TestStatusEndpoint:
    def test_status_reports_enabled(self):
        from fleet_platform.api.routes import agent

        db = AsyncMock()
        with patch.object(agent, "is_agent_enabled", new=AsyncMock(return_value=True)):
            result = asyncio.run(agent.agent_status(db=db, claims={"role": "admin"}))
        assert result == {"enabled": True}

    def test_status_reports_disabled(self):
        from fleet_platform.api.routes import agent

        db = AsyncMock()
        with patch.object(agent, "is_agent_enabled", new=AsyncMock(return_value=False)):
            result = asyncio.run(agent.agent_status(db=db, claims={"role": "admin"}))
        assert result == {"enabled": False}
