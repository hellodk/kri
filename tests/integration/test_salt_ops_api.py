# tests/integration/test_salt_ops_api.py
"""Integration tests for the salt-ops API routes.

Salt state application and ad-hoc commands enqueue Celery tasks, so
we patch the task objects to avoid needing a live Salt master or broker.
"""

from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


# ── /api/v1/salt/states ───────────────────────────────────────────────


async def test_list_states_returns_list(admin_client: AsyncClient):
    resp = await admin_client.get("/api/v1/salt/states")
    assert resp.status_code == 200
    data = resp.json()
    assert "states" in data
    assert isinstance(data["states"], list)


async def test_list_states_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/salt/states")
    assert resp.status_code == 401


async def test_list_states_viewer_allowed(viewer_client: AsyncClient):
    # /states only requires get_current_user (any authenticated user)
    resp = await viewer_client.get("/api/v1/salt/states")
    assert resp.status_code == 200


# ── /api/v1/salt/apply ────────────────────────────────────────────────


async def test_apply_state_validates_body_missing_fields(admin_client: AsyncClient):
    """POST with an empty body must return 422 (missing required fields)."""
    resp = await admin_client.post("/api/v1/salt/apply", json={})
    assert resp.status_code == 422


async def test_apply_state_validates_empty_minion_ids(admin_client: AsyncClient):
    """POST with empty minion_ids list must return 422."""
    resp = await admin_client.post(
        "/api/v1/salt/apply",
        json={"state": "base.bootstrap", "minion_ids": []},
    )
    assert resp.status_code == 422


async def test_apply_state_enqueues_task(admin_client: AsyncClient):
    """Valid POST returns 202 with a task_id."""
    fake_task = MagicMock()
    fake_task.id = "fake-task-id-apply"
    # #749: route enqueues by task name via celery_app.send_task (imported from
    # fleet_platform.workers.celery_app at call time), not apply_salt_state.delay().
    with patch(
        "fleet_platform.workers.celery_app.celery_app.send_task",
        return_value=fake_task,
    ):
        resp = await admin_client.post(
            "/api/v1/salt/apply",
            json={"state": "base.bootstrap", "minion_ids": ["mac-mini-01"]},
        )
    assert resp.status_code == 202
    data = resp.json()
    assert "task_id" in data
    assert data["task_id"] == "fake-task-id-apply"


async def test_apply_state_requires_operator(viewer_client: AsyncClient):
    """Viewer role must be rejected with 403."""
    resp = await viewer_client.post(
        "/api/v1/salt/apply",
        json={"state": "base.bootstrap", "minion_ids": ["mac-mini-01"]},
    )
    assert resp.status_code == 403


# ── /api/v1/salt/cmd ─────────────────────────────────────────────────


async def test_cmd_validates_body_missing_fields(admin_client: AsyncClient):
    """POST /cmd with an empty body must return 422."""
    resp = await admin_client.post("/api/v1/salt/cmd", json={})
    assert resp.status_code == 422


async def test_cmd_rejects_disallowed_function(admin_client: AsyncClient):
    """POST /cmd with a function not in the allowlist must return 422."""
    resp = await admin_client.post(
        "/api/v1/salt/cmd",
        json={"function": "cmd.run_all", "minion_ids": ["mac-mini-01"]},
    )
    assert resp.status_code == 422


async def test_cmd_validates_empty_minion_ids(admin_client: AsyncClient):
    """POST /cmd with empty minion_ids list must return 422."""
    resp = await admin_client.post(
        "/api/v1/salt/cmd",
        json={"function": "grains.items", "minion_ids": []},
    )
    assert resp.status_code == 422


async def test_cmd_enqueues_task(admin_client: AsyncClient):
    """Valid POST returns 202 with a task_id."""
    fake_task = MagicMock()
    fake_task.id = "fake-task-id-cmd"
    # #749: route enqueues by task name via celery_app.send_task, not run_salt_cmd.delay().
    with patch(
        "fleet_platform.workers.celery_app.celery_app.send_task",
        return_value=fake_task,
    ):
        resp = await admin_client.post(
            "/api/v1/salt/cmd",
            json={"function": "grains.items", "minion_ids": ["mac-mini-01"]},
        )
    assert resp.status_code == 202
    data = resp.json()
    assert "task_id" in data
    assert data["task_id"] == "fake-task-id-cmd"


async def test_cmd_requires_operator(viewer_client: AsyncClient):
    """Viewer role must be rejected with 403."""
    resp = await viewer_client.post(
        "/api/v1/salt/cmd",
        json={"function": "grains.items", "minion_ids": ["mac-mini-01"]},
    )
    assert resp.status_code == 403
