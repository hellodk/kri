"""Issue #977 — Master-promotion Phase C: attach-minions (re-point additively).

Covers:
- ``_additive_master_list`` pure helper (dedup, order preservation, self re-point).
- source-contract: ``reconfigure_minions`` exists, calls ``key.accept`` with
  ``match=minion_id``, and sets ``node.salt_master_id``.
- route: ``POST /masters/{id}/attach-minions`` exists, requires admin, 422s on
  empty ``node_ids``, and enqueues the task via ``celery_app.send_task``.
"""

import asyncio
import inspect
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import params as fa_params

from fleet_platform.workers import ansible_tasks

_ANSIBLE_TASKS_SRC = Path(ansible_tasks.__file__).read_text()


# ---------------------------------------------------------------------------
# 1. _additive_master_list — pure helper, no DB
# ---------------------------------------------------------------------------


class TestAdditiveMasterList:
    def test_distinct_addresses_preserve_order(self):
        result = ansible_tasks._additive_master_list("10.0.0.1", "10.0.0.2")
        assert result == ["10.0.0.1", "10.0.0.2"]

    def test_same_address_dedups_to_single_entry(self):
        result = ansible_tasks._additive_master_list("10.0.0.1", "10.0.0.1")
        assert result == ["10.0.0.1"]

    def test_no_current_master_yields_target_only(self):
        result = ansible_tasks._additive_master_list(None, "10.0.0.2")
        assert result == ["10.0.0.2"]

    def test_falsy_current_master_filtered(self):
        result = ansible_tasks._additive_master_list("", "10.0.0.2")
        assert result == ["10.0.0.2"]


# ---------------------------------------------------------------------------
# 2. reconfigure_minions — source-contract checks
# ---------------------------------------------------------------------------


class TestReconfigureMinionsSourceContract:
    def test_reconfigure_minions_exists(self):
        assert hasattr(ansible_tasks, "reconfigure_minions")
        sig = inspect.signature(ansible_tasks.reconfigure_minions.__wrapped__)
        params = list(sig.parameters)
        assert "master_id" in params
        assert "node_ids" in params

    def test_calls_key_accept_scoped_to_minion_id(self):
        """key.accept must be scoped with match=minion_id, not accept-all."""
        assert 'run_wheel(target_master, "key.accept", match=minion_id)' in _ANSIBLE_TASKS_SRC

    def test_sets_node_salt_master_id(self):
        assert "_n.salt_master_id = target_uuid" in _ANSIBLE_TASKS_SRC

    def test_registered_as_celery_task(self):
        assert ansible_tasks.reconfigure_minions.name == "fleet_platform.workers.ansible_tasks.reconfigure_minions"


# ---------------------------------------------------------------------------
# 3. /attach-minions route
# ---------------------------------------------------------------------------


class TestAttachMinionsRoute:
    def test_route_exists_in_router(self):
        from fleet_platform.api.routes.salt_masters import router

        routes = [r.path for r in router.routes]
        attach_paths = [p for p in routes if "attach-minions" in p]
        assert attach_paths, f"No /attach-minions route found in router. Routes: {routes}"

    def test_route_requires_admin(self):
        from fleet_platform.api.routes.salt_masters import attach_minions

        sig = inspect.signature(attach_minions)
        for param in sig.parameters.values():
            if isinstance(param.default, fa_params.Depends):
                dep = param.default.dependency
                if getattr(dep, "__qualname__", "").endswith("require_role.<locals>.dependency"):
                    if hasattr(dep, "__closure__") and dep.__closure__:
                        for cell in dep.__closure__:
                            try:
                                val = cell.cell_contents
                                if isinstance(val, set) and "admin" in val:
                                    return
                            except ValueError:
                                pass
        pytest.fail("attach_minions must use require_role('admin')")

    def test_route_422s_on_empty_node_ids(self):
        from fastapi import HTTPException

        from fleet_platform.api.routes.salt_masters import AttachMinionsRequest, attach_minions

        master_id = uuid.uuid4()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = MagicMock(id=master_id)
        mock_db.execute = AsyncMock(return_value=mock_result)

        body = AttachMinionsRequest(node_ids=[])

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(attach_minions(master_id=master_id, body=body, db=mock_db))
        assert exc_info.value.status_code == 422

    def test_route_404s_when_master_missing(self):
        from fastapi import HTTPException

        from fleet_platform.api.routes.salt_masters import AttachMinionsRequest, attach_minions

        master_id = uuid.uuid4()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        body = AttachMinionsRequest(node_ids=["node-1"])

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(attach_minions(master_id=master_id, body=body, db=mock_db))
        assert exc_info.value.status_code == 404

    def test_route_enqueues_reconfigure_minions_via_send_task(self):
        from fleet_platform.api.routes.salt_masters import AttachMinionsRequest, attach_minions

        master_id = uuid.uuid4()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = MagicMock(id=master_id)
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_task = MagicMock()
        mock_task.id = "task-abc-123"
        mock_celery = MagicMock()
        mock_celery.send_task.return_value = mock_task

        body = AttachMinionsRequest(node_ids=["node-1", "node-2"])

        with patch("fleet_platform.workers.celery_app.celery_app", mock_celery):
            result = asyncio.run(attach_minions(master_id=master_id, body=body, db=mock_db))

        mock_celery.send_task.assert_called_once()
        call_args = mock_celery.send_task.call_args
        task_name = call_args[0][0] if call_args[0] else ""
        assert "reconfigure_minions" in task_name
        call_task_args = call_args[0][1] if len(call_args[0]) > 1 else call_args.kwargs.get("args")
        assert call_task_args == [str(master_id), ["node-1", "node-2"]]
        assert result["status"] == "queued"
        assert result["count"] == 2
