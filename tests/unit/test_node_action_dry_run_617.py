"""Tests for node action dry_run mode (issue #617)."""

from fleet_platform.api.routes.node_actions import NodeActionRequest


def test_node_action_request_dry_run_defaults_false():
    """NodeActionRequest.dry_run defaults to False."""
    req = NodeActionRequest(action_type="process_stop")
    assert req.dry_run is False


def test_node_action_request_dry_run_explicit_true():
    """NodeActionRequest.dry_run can be set to True."""
    req = NodeActionRequest(action_type="process_stop", dry_run=True)
    assert req.dry_run is True


def test_node_action_request_dry_run_explicit_false():
    """NodeActionRequest.dry_run can be explicitly set to False."""
    req = NodeActionRequest(action_type="service_stop", dry_run=False)
    assert req.dry_run is False


def test_node_action_request_with_params():
    """NodeActionRequest.dry_run works with params."""
    req = NodeActionRequest(
        action_type="process_stop",
        params={"pid": "1234"},
        dry_run=True,
    )
    assert req.dry_run is True
    assert req.params == {"pid": "1234"}


def test_node_actions_py_contains_dry_run_field():
    """NodeActionRequest must have dry_run field with default False."""
    from fleet_platform.api.routes.node_actions import NodeActionRequest

    field = NodeActionRequest.model_fields.get("dry_run")
    assert field is not None, "NodeActionRequest must have a dry_run field"
    assert field.default is False, f"NodeActionRequest.dry_run must default to False, got {field.default!r}"


def test_node_actions_py_has_dry_run_branch():
    """POSTing a dry_run=True action must return status='dry_run' without dispatching anything.

    Drive the real endpoint through the ASGI stack (matching the behavioral style in
    test_nondestructive_action_dispatch_628.py) and assert the dry-run response — and
    that no Salt task is dispatched and no DB rows are added.
    """
    import asyncio
    import uuid
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from httpx import ASGITransport, AsyncClient

    from fleet_platform.api import deps
    from fleet_platform.api.limiter import limiter
    from fleet_platform.api.main import create_app
    from fleet_platform.core.auth import create_access_token

    class _FakeResult:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

    class _FakeSession:
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

    async def _run():
        limiter._storage.reset()
        node = SimpleNamespace(minion_id="minion-xyz")
        session = _FakeSession(node)
        app = create_app()

        async def _override_db():
            yield session

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        async def _override_redis():
            return mock_redis

        app.dependency_overrides[deps.get_db] = _override_db
        app.dependency_overrides[deps.get_redis] = _override_redis

        token = create_access_token(user_id=str(uuid.uuid4()), email="operator@test.local", role="operator")
        with patch("fleet_platform.workers.celery_app.celery_app.send_task") as send_task:
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://testserver",
                headers={"Authorization": f"Bearer {token}"},
            ) as client:
                resp = await client.post(
                    f"/api/v1/nodes/{uuid.uuid4()}/actions",
                    json={"action_type": "process_stop", "params": {"pid": "1234"}, "dry_run": True},
                )
        limiter._storage.reset()

        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["status"] == "dry_run", f"dry_run=True must return status='dry_run', got {body!r}"
        assert "No action created, no email sent" in body["message"], (
            f"dry_run response must include 'No action created, no email sent', got {body['message']!r}"
        )
        # No side effects: no Salt task dispatched, no rows added to the session.
        assert not send_task.called, "dry_run must not dispatch a Salt task"
        assert session.added == [], "dry_run must not create any DB rows"

    asyncio.run(_run())


def test_dry_run_does_not_bypass_param_validation():
    """dry_run=True must not short-circuit _validate_action_params — invalid pid must still yield 422."""
    import asyncio
    import uuid
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from httpx import ASGITransport, AsyncClient

    from fleet_platform.api import deps
    from fleet_platform.api.limiter import limiter
    from fleet_platform.api.main import create_app
    from fleet_platform.core.auth import create_access_token

    class _FakeResult:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

    class _FakeSession:
        def __init__(self, node):
            self._node = node

        async def execute(self, *args, **kwargs):
            return _FakeResult(self._node)

        async def commit(self):
            pass

        async def rollback(self):
            pass

    async def _run():
        limiter._storage.reset()
        node = SimpleNamespace(minion_id="minion-xyz")
        session = _FakeSession(node)
        app = create_app()

        async def _override_db():
            yield session

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        async def _override_redis():
            return mock_redis

        app.dependency_overrides[deps.get_db] = _override_db
        app.dependency_overrides[deps.get_redis] = _override_redis

        token = create_access_token(user_id=str(uuid.uuid4()), email="operator@test.local", role="operator")
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            resp = await client.post(
                f"/api/v1/nodes/{uuid.uuid4()}/actions",
                json={"action_type": "process_stop", "params": {"pid": "not-a-pid"}, "dry_run": True},
            )
        limiter._storage.reset()

        assert resp.status_code == 422, (
            f"dry_run=True must not bypass _validate_action_params — "
            f"invalid pid must return 422, got {resp.status_code}: {resp.text}"
        )

    asyncio.run(_run())


def test_dry_run_does_not_bypass_node_not_found():
    """dry_run=True on a non-existent node must return 404, not 202 dry_run."""
    import asyncio
    import uuid
    from unittest.mock import AsyncMock

    from httpx import ASGITransport, AsyncClient

    from fleet_platform.api import deps
    from fleet_platform.api.limiter import limiter
    from fleet_platform.api.main import create_app
    from fleet_platform.core.auth import create_access_token

    class _FakeResult:
        def scalar_one_or_none(self):
            return None

    class _FakeSession:
        async def execute(self, *args, **kwargs):
            return _FakeResult()

        async def commit(self):
            pass

        async def rollback(self):
            pass

    async def _run():
        limiter._storage.reset()
        session = _FakeSession()
        app = create_app()

        async def _override_db():
            yield session

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        async def _override_redis():
            return mock_redis

        app.dependency_overrides[deps.get_db] = _override_db
        app.dependency_overrides[deps.get_redis] = _override_redis

        token = create_access_token(user_id=str(uuid.uuid4()), email="operator@test.local", role="operator")
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            # harden has no per-target params to validate, so it reaches the node lookup
            resp = await client.post(
                f"/api/v1/nodes/{uuid.uuid4()}/actions",
                json={"action_type": "harden", "params": {}, "dry_run": True},
            )
        limiter._storage.reset()

        assert resp.status_code == 404, (
            f"dry_run=True must not bypass node 404 check — "
            f"non-existent node must return 404, got {resp.status_code}: {resp.text}"
        )

    asyncio.run(_run())
