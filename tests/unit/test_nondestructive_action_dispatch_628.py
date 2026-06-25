"""Unit tests for non-destructive Salt dispatch and service_enable mapping — #628."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from fleet_platform.api import deps
from fleet_platform.api.limiter import limiter
from fleet_platform.api.main import create_app
from fleet_platform.api.routes.node_actions import _build_salt_invocation
from fleet_platform.core.auth import create_access_token

# ---------------------------------------------------------------------------
# _build_salt_invocation — service_enable mapping (#628 addition)
# ---------------------------------------------------------------------------


class TestServiceEnableMapping:
    def test_service_enable_maps_to_service_enable(self):
        fn, args = _build_salt_invocation("service_enable", {"service": "com.x"})
        assert fn == "service.enable"
        assert args == ["com.x"]

    def test_service_enable_args_is_list_with_service_name(self):
        _, args = _build_salt_invocation("service_enable", {"service": "com.example.app"})
        assert isinstance(args, list)
        assert len(args) == 1
        assert args[0] == "com.example.app"


# ---------------------------------------------------------------------------
# Existing mappings still hold after the service_enable addition
# ---------------------------------------------------------------------------


class TestExistingMappingsStillHold:
    def test_service_start_still_maps(self):
        fn, args = _build_salt_invocation("service_start", {"service": "nginx"})
        assert fn == "service.start"
        assert args == ["nginx"]

    def test_service_restart_still_maps(self):
        fn, args = _build_salt_invocation("service_restart", {"service": "nginx"})
        assert fn == "service.restart"
        assert args == ["nginx"]

    def test_service_stop_still_maps(self):
        fn, args = _build_salt_invocation("service_stop", {"service": "nginx"})
        assert fn == "service.stop"
        assert args == ["nginx"]

    def test_service_disable_still_maps(self):
        fn, args = _build_salt_invocation("service_disable", {"service": "com.example.myapp"})
        assert fn == "service.disable"
        assert args == ["com.example.myapp"]

    def test_process_resume_maps_to_sigcont_signal_19(self):
        fn, args = _build_salt_invocation("process_resume", {"pid": 42})
        assert fn == "ps.kill_pid"
        assert args == ["42", "signal=19"]

    def test_unknown_service_action_still_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _build_salt_invocation("service_nuke", {"service": "foo"})
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Behavioral: the non-destructive branch of request_node_action really dispatches
# a Salt command via celery_app.send_task (by task name) using the
# _build_salt_invocation mapping — not a placeholder. Previously this contract was
# checked by grepping node_actions.py for substrings ("salt_tasks.run_salt_cmd",
# "_build_salt_invocation(payload.action_type", "actual Salt call TBD"); those
# pass even if the dispatch is broken. Here we drive the real endpoint through the
# ASGI stack with celery_app.send_task patched and assert the actual call.
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeSession:
    """Minimal async session: returns the configured node for the lookup, swallows writes."""

    def __init__(self, node):
        self._node = node
        self.added: list = []

    async def execute(self, *args, **kwargs):
        return _FakeResult(self._node)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def rollback(self):
        pass


class TestNonDestructiveBranchDispatch:
    @pytest.fixture
    async def dispatch_ctx(self):
        """Yield (client, send_task_mock, node) wired to a real app with mocked deps."""
        limiter._storage.reset()  # avoid 429 bleed from other tests (request route is 5/minute)
        node = SimpleNamespace(minion_id="minion-xyz")
        app = create_app()

        async def _override_db():
            yield _FakeSession(node)

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        async def _override_redis():
            return mock_redis

        app.dependency_overrides[deps.get_db] = _override_db
        app.dependency_overrides[deps.get_redis] = _override_redis

        token = create_access_token(user_id=str(uuid.uuid4()), email="operator@test.local", role="operator")
        with patch("fleet_platform.workers.celery_app.celery_app.send_task") as send_task:
            send_task.return_value = SimpleNamespace(id="task-123")
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://testserver",
                headers={"Authorization": f"Bearer {token}"},
            ) as client:
                yield client, send_task, node
        limiter._storage.reset()

    async def test_dispatches_run_salt_cmd_by_task_name(self, dispatch_ctx):
        client, send_task, _node = dispatch_ctx
        resp = await client.post(
            f"/api/v1/nodes/{uuid.uuid4()}/actions",
            json={"action_type": "service_start", "params": {"service": "nginx"}},
        )
        assert resp.status_code == 202, resp.text
        send_task.assert_called_once()
        task_name = send_task.call_args.args[0]
        assert task_name == "fleet_platform.workers.salt_tasks.run_salt_cmd", (
            f"non-destructive branch must dispatch run_salt_cmd by name, got {task_name!r}"
        )

    async def test_dispatch_kwargs_match_build_salt_invocation(self, dispatch_ctx):
        client, send_task, node = dispatch_ctx
        resp = await client.post(
            f"/api/v1/nodes/{uuid.uuid4()}/actions",
            json={"action_type": "service_start", "params": {"service": "nginx"}},
        )
        assert resp.status_code == 202, resp.text
        # The dispatched (function, args) must equal what _build_salt_invocation maps.
        expected_fn, expected_args = _build_salt_invocation("service_start", {"service": "nginx"})
        kwargs = send_task.call_args.kwargs["kwargs"]
        assert kwargs["function"] == expected_fn == "service.start"
        assert kwargs["args"] == expected_args == ["nginx"]
        assert kwargs["target_minions"] == [node.minion_id]

    async def test_branch_executes_not_placeholder(self, dispatch_ctx):
        client, send_task, _node = dispatch_ctx
        resp = await client.post(
            f"/api/v1/nodes/{uuid.uuid4()}/actions",
            json={"action_type": "service_start", "params": {"service": "nginx"}},
        )
        # A placeholder ("actual Salt call TBD") would never dispatch and never
        # report executed; assert both the real dispatch and the executed status.
        assert resp.status_code == 202, resp.text
        assert resp.json()["status"] == "executed"
        assert send_task.called, "non-destructive branch must actually dispatch a Salt task, not no-op"
