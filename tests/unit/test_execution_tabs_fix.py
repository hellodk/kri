"""Tests for #299 — group-targeted jobs appear in node's Executions tab."""

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock


def _make_job_mock(target_id: str, target_type: str = "group") -> MagicMock:
    job = MagicMock()
    job.id = uuid.uuid4()
    job.playbook = "deploy.yml"
    job.target_type = target_type
    job.target_id = uuid.UUID(target_id)
    job.target_label = "test-target"
    job.extravars = {}
    job.status = "completed"
    job.triggered_by = "admin"
    job.started_at = None
    job.completed_at = None
    job.stdout = None
    job.rc = 0
    job.timeout_seconds = 1800
    job.created_at = datetime.now(timezone.utc)
    job.celery_task_id = None
    job.cancelled_at = None
    return job


def test_list_ansible_jobs_route_has_group_logic():
    """list_ansible_jobs must include group-targeted jobs when filtering by node_id."""

    async def _run():
        from fleet_platform.api.routes.ansible import list_ansible_jobs

        node_id = str(uuid.uuid4())
        group_id = str(uuid.uuid4())
        group_job = _make_job_mock(group_id, "group")

        # DB execute call 1: group membership query → returns one group_id
        group_result = MagicMock()
        group_result.scalars.return_value.all.return_value = [uuid.UUID(group_id)]

        # DB execute call 2: job list query → returns the group-targeted job
        job_result = MagicMock()
        job_result.scalars.return_value.all.return_value = [group_job]

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[group_result, job_result])

        results = await list_ansible_jobs(node_id=node_id, page=1, per_page=25, db=db, _={})

        assert len(results) == 1, "Group-targeted job must appear when querying by node_id"
        assert str(results[0].target_id) == group_id, "Returned job must be the group-targeted one"

    asyncio.run(_run())


def test_list_ansible_jobs_uses_or_condition():
    """Jobs for groups containing the node must be OR'd into the query (both direct and group jobs returned)."""

    async def _run():
        from fleet_platform.api.routes.ansible import list_ansible_jobs

        node_id = str(uuid.uuid4())
        group_id = str(uuid.uuid4())
        direct_job = _make_job_mock(node_id, "node")
        group_job = _make_job_mock(group_id, "group")

        group_result = MagicMock()
        group_result.scalars.return_value.all.return_value = [uuid.UUID(group_id)]

        # Both direct and group-targeted jobs returned from the OR'd query
        job_result = MagicMock()
        job_result.scalars.return_value.all.return_value = [direct_job, group_job]

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[group_result, job_result])

        results = await list_ansible_jobs(node_id=node_id, page=1, per_page=25, db=db, _={})

        assert len(results) == 2, (
            f"OR query must return both direct-node and group-targeted jobs; got {len(results)} result(s)"
        )
        target_ids = {str(r.target_id) for r in results}
        assert node_id in target_ids, "Direct job must be included"
        assert group_id in target_ids, "Group job must be included via OR condition"

    asyncio.run(_run())
