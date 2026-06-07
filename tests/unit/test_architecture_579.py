"""Architecture hardening — issue #579.

Two structural fixes are verified here, all without a live DB/broker:

1. Queue isolation: long-running ansible jobs (run_playbook, bootstrap_node,
   provision_master) route to a dedicated ``ansible`` queue, consumed by a
   dedicated worker, so they can no longer starve the fast control-plane
   ``maintenance`` queue (poll_salt_masters, presence sync, reapers, health).
   The worker launch configs (compose / k8s / systemd) are asserted at the
   source so the queue split is actually deployed, not just routed.

2. Default-master integrity: ``delete_salt_master`` refuses to delete the
   ``is_default`` master (caller must promote another first) -> 409, and a
   partial-unique migration guarantees at most one ``is_default=true`` row.
"""

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from fleet_platform.workers.celery_app import celery_app

# Force-import every task module listed in celery_app.include so all task
# names are registered before routing is resolved.
celery_app.loader.import_default_modules()

REPO_ROOT = Path(__file__).resolve().parents[2]

ANSIBLE_QUEUE = "ansible"
CONTROL_QUEUE = "maintenance"

LONG_TASKS = [
    "fleet_platform.workers.playbook_tasks.run_playbook",
    "fleet_platform.workers.ansible_tasks.bootstrap_node",
    "fleet_platform.workers.ansible_tasks.provision_master",
]
CONTROL_TASKS = [
    "fleet_platform.workers.maintenance.poll_salt_masters",
    "fleet_platform.workers.salt_presence_tasks.sync_minion_presence",
    "fleet_platform.workers.maintenance.reap_orphaned_jobs",
]


def _effective_queue(task_name: str) -> str:
    """Resolve the queue a task is actually sent to.

    Mirrors apply_async: the task's decorator ``queue`` becomes an option that
    is merged with task_routes, so this catches both routing mechanisms.
    """
    task = celery_app.tasks[task_name]
    opts = {"queue": task.queue} if getattr(task, "queue", None) else {}
    route = celery_app.amqp.router.route(opts, task_name)
    q = route.get("queue")
    return getattr(q, "name", q)


# ---------------------------------------------------------------------------
# 1. Queue routing
# ---------------------------------------------------------------------------


class TestQueueRouting:
    @pytest.mark.parametrize("task_name", LONG_TASKS)
    def test_long_tasks_route_to_ansible_queue(self, task_name):
        assert _effective_queue(task_name) == ANSIBLE_QUEUE

    @pytest.mark.parametrize("task_name", CONTROL_TASKS)
    def test_control_plane_tasks_stay_on_maintenance(self, task_name):
        assert _effective_queue(task_name) == CONTROL_QUEUE

    @pytest.mark.parametrize("task_name", LONG_TASKS)
    def test_task_routes_pin_long_tasks_to_ansible(self, task_name):
        routes = celery_app.conf.task_routes or {}
        assert routes.get(task_name) == {"queue": ANSIBLE_QUEUE}


# ---------------------------------------------------------------------------
# 2. Worker launch configs (source assertions across all three deploy modes)
# ---------------------------------------------------------------------------


class TestWorkerLaunchConfigs:
    def test_compose_has_dedicated_ansible_worker(self):
        text = (REPO_ROOT / "deploy" / "docker-compose.yml").read_text()
        assert "worker-ansible:" in text
        # The ansible worker consumes only the ansible queue at concurrency 2.
        assert '"--queues", "ansible"' in text
        assert '"--concurrency", "2"' in text

    def test_compose_plain_worker_drops_ansible_queue(self):
        text = (REPO_ROOT / "deploy" / "docker-compose.yml").read_text()
        assert '"--queues", "default,maintenance,drift,sbom"' in text
        # The plain worker must not also consume the ansible queue.
        assert '"default,maintenance,drift,sbom,ansible"' not in text

    def test_k8s_has_dedicated_ansible_worker_deployment(self):
        text = (REPO_ROOT / "deploy" / "k8s" / "worker-ansible-deployment.yaml").read_text()
        assert "kri-worker-ansible" in text
        assert "--queues=ansible" in text
        assert "--concurrency=2" in text

    def test_k8s_plain_worker_drops_ansible_queue(self):
        text = (REPO_ROOT / "deploy" / "k8s" / "worker-deployment.yaml").read_text()
        assert "--queues=default,maintenance,drift,sbom" in text
        assert "ansible" not in text.split("--queues=")[1].splitlines()[0]

    def test_systemd_has_dedicated_ansible_worker_unit(self):
        text = (REPO_ROOT / "deploy" / "systemd" / "kri-worker-ansible.service").read_text()
        assert "--queues ansible" in text
        assert "--concurrency 2" in text

    def test_systemd_plain_worker_drops_ansible_queue(self):
        text = (REPO_ROOT / "deploy" / "systemd" / "kri-worker.service").read_text()
        assert "--queues default,maintenance,drift,sbom" in text
        assert "default,maintenance,drift,sbom,ansible" not in text


# ---------------------------------------------------------------------------
# 3. Default-master delete guard
# ---------------------------------------------------------------------------


def _make_master(**kwargs) -> SimpleNamespace:
    defaults = dict(
        id=uuid.uuid4(),
        name="default-master",
        enabled=True,
        is_default=True,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _result(value):
    r = AsyncMock()
    r.scalar_one_or_none = lambda: value
    return r


class TestDefaultMasterDeleteGuard:
    @pytest.mark.asyncio
    async def test_delete_default_master_raises_409(self):
        from fastapi import HTTPException

        from fleet_platform.api.routes.salt_masters import delete_salt_master

        master = _make_master(is_default=True)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(master))

        with pytest.raises(HTTPException) as exc_info:
            await delete_salt_master(master_id=master.id, db=db, _={"sub": "admin"})

        assert exc_info.value.status_code == 409
        assert "default" in exc_info.value.detail.lower()
        db.delete.assert_not_called()


# ---------------------------------------------------------------------------
# 4. Partial-unique migration for exactly-one-default
# ---------------------------------------------------------------------------


class TestOneDefaultMigration:
    def test_migration_046_partial_unique_present(self):
        path = REPO_ROOT / "fleet_platform" / "db" / "migrations" / "versions"
        candidates = list(path.glob("046_*.py"))
        assert candidates, "expected a 046_* migration for the one-default index"
        text = candidates[0].read_text()
        assert 'revision = "046"' in text
        assert 'down_revision = "045"' in text
        assert "is_default" in text
        # Partial-unique: a UNIQUE index restricted to is_default = true.
        assert "unique" in text.lower()
        assert "where" in text.lower()
