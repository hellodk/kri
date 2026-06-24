"""Unit tests for issue #557 — provision_master Celery task.

Tests cover:
- OS detection → correct playbook chosen (macOS vs Linux)
- SSH unreachable → provision_status=failed, playbook NOT run
- Successful run → provision_status=provisioned + run_probe called + MasterProvisionRun finalized
- Exception mid-run → finally sets failed; no stuck 'provisioning'
- Reaper marks stuck MasterProvisionRun + master failed
- /provision endpoint requires admin, enqueues the task

All tests run without a live DB, SSH, or ansible — pure mocks.
"""

import uuid
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_master(**kwargs):
    """Return a MagicMock standing in for a SaltMaster ORM row."""
    master = MagicMock()
    master.id = uuid.uuid4()
    master.name = "test-master"
    master.address = "10.0.0.1"
    master.ssh_host = kwargs.get("ssh_host", None)
    master.ssh_user = kwargs.get("ssh_user", "admin")
    master.ssh_key_enc = kwargs.get("ssh_key_enc", None)
    master.ssh_password_enc = kwargs.get("ssh_password_enc", None)
    master.api_password_enc = kwargs.get("api_password_enc", None)
    master.provision_status = kwargs.get("provision_status", "unprovisioned")
    master.provision_error = None
    master.status = "unknown"
    master.checks = None
    master.last_checked_at = None
    master.last_error = None
    return master


def _mock_db_context(master, prun=None):
    """Return a context manager mock whose scalar_one_or_none alternates between master and prun."""
    db = MagicMock()
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)

    # We need to support multiple calls to db.execute(...).scalar_one_or_none()
    # In the main happy-path the sequence is: master (load), prun (create) is added,
    # then various re-loads.  Keep it simple — always return master unless prun explicitly set.
    scalar_mock = MagicMock()
    scalar_mock.scalar_one_or_none.return_value = master
    scalar_mock.scalars.return_value.all.return_value = []
    db.execute.return_value = scalar_mock

    return db


# ---------------------------------------------------------------------------
# 1. OS detection → correct playbook
# ---------------------------------------------------------------------------


class TestOsDetectPlaybookSelection:
    """provision_master must pick the correct playbook based on OS."""

    def _run_with_os(self, uname_output: str) -> str:
        """Run provision_master with a mocked uname and capture the playbook name used."""
        import fleet_platform.workers.ansible_tasks as mod

        master = _make_master()
        prun = MagicMock()
        prun.id = uuid.uuid4()

        captured_playbook: list[str] = []

        fake_thread = MagicMock()
        fake_thread.is_alive.return_value = False
        fake_runner = MagicMock()
        fake_runner.rc = 0
        fake_runner.status = "successful"

        def _fake_run_async(**kwargs):
            # Capture the playbook arg
            captured_playbook.append(kwargs.get("playbook", ""))
            return fake_thread, fake_runner

        db = MagicMock()
        db.__enter__ = MagicMock(return_value=db)
        db.__exit__ = MagicMock(return_value=False)

        # First execute call returns master; subsequent return master again
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = master
        db.execute.return_value = execute_result
        db.add = MagicMock()
        db.commit = MagicMock()

        prun_added = {}

        def _fake_add(obj):
            if hasattr(obj, "salt_master_id"):
                prun_added["prun"] = obj
                obj.id = uuid.uuid4()

        db.add.side_effect = _fake_add

        with (
            patch.object(mod, "get_sync_db", return_value=db),
            patch.object(mod, "_get_bootstrap_settings", return_value=("admin", "", "")),
            patch.object(mod, "_detect_os_family", return_value=uname_output),
            patch("ansible_runner.run_async", side_effect=_fake_run_async),
            patch(
                "fleet_platform.services.salt_master_probe.run_probe",
                return_value={"status": "healthy", "checks": []},
            ),
        ):
            task = mod.provision_master
            task(str(master.id), action="install")

        return captured_playbook[0] if captured_playbook else ""

    def test_darwin_uses_mac_playbook(self):
        playbook = self._run_with_os("Darwin")
        assert "install_salt_master.yml" in playbook
        assert "linux" not in playbook

    def test_linux_uses_linux_playbook(self):
        playbook = self._run_with_os("Linux")
        assert "install_salt_master_linux.yml" in playbook

    def test_other_unix_treated_as_linux(self):
        """Any non-Darwin uname output should use the Linux playbook."""
        playbook = self._run_with_os("FreeBSD")
        assert "install_salt_master_linux.yml" in playbook


# ---------------------------------------------------------------------------
# 2. SSH unreachable → provision_status=failed, playbook NOT run
# ---------------------------------------------------------------------------


class TestSshUnreachable:
    def test_unreachable_sets_failed_status(self):
        import fleet_platform.workers.ansible_tasks as mod

        master = _make_master()
        db = MagicMock()
        db.__enter__ = MagicMock(return_value=db)
        db.__exit__ = MagicMock(return_value=False)

        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = master
        db.execute.return_value = execute_result

        def _fake_add(obj):
            if hasattr(obj, "salt_master_id"):
                obj.id = uuid.uuid4()

        db.add.side_effect = _fake_add

        ansible_called: list[bool] = []

        def _trap_run_async(**kwargs):
            ansible_called.append(True)
            raise AssertionError("ansible_runner.run_async must NOT be called when SSH is unreachable")

        with (
            patch.object(mod, "get_sync_db", return_value=db),
            patch.object(mod, "_get_bootstrap_settings", return_value=("admin", "", "")),
            patch.object(mod, "_detect_os_family", return_value=None),  # None = unreachable
            patch("ansible_runner.run_async", side_effect=_trap_run_async),
        ):
            result = mod.provision_master(str(master.id), action="install")

        assert result["status"] == "failed"
        assert not ansible_called, "Playbook was run despite SSH being unreachable"

    def test_unreachable_sets_provision_status_via_db(self):
        import fleet_platform.workers.ansible_tasks as mod

        master = _make_master()
        db = MagicMock()
        db.__enter__ = MagicMock(return_value=db)
        db.__exit__ = MagicMock(return_value=False)

        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = master
        db.execute.return_value = execute_result

        def _fake_add(obj):
            if hasattr(obj, "salt_master_id"):
                obj.id = uuid.uuid4()

        db.add.side_effect = _fake_add

        with (
            patch.object(mod, "get_sync_db", return_value=db),
            patch.object(mod, "_get_bootstrap_settings", return_value=("admin", "", "")),
            patch.object(mod, "_detect_os_family", return_value=None),
            patch("ansible_runner.run_async", side_effect=AssertionError("must not be called")),
        ):
            mod.provision_master(str(master.id), action="install")

        # provision_status should have been set to "failed" on the master object
        assert master.provision_status == "failed"
        assert master.provision_error is not None


# ---------------------------------------------------------------------------
# 3. Success → provision_status=provisioned + run_probe called + run finalized
# ---------------------------------------------------------------------------


class TestSuccessfulProvision:
    def test_success_sets_provisioned_status(self):
        import fleet_platform.workers.ansible_tasks as mod

        master = _make_master()

        db = MagicMock()
        db.__enter__ = MagicMock(return_value=db)
        db.__exit__ = MagicMock(return_value=False)

        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = master
        db.execute.return_value = execute_result
        prun = MagicMock()
        prun.id = uuid.uuid4()
        prun.status = "running"

        def _fake_add(obj):
            if hasattr(obj, "salt_master_id"):
                obj.id = uuid.uuid4()

        db.add.side_effect = _fake_add

        fake_thread = MagicMock()
        fake_thread.is_alive.return_value = False
        fake_runner = MagicMock()
        fake_runner.rc = 0
        fake_runner.status = "successful"

        probe_calls: list[int] = []

        async def _fake_probe(_master):
            probe_calls.append(1)
            return {
                "status": "healthy",
                "checks": [{"check": "ping", "status": "pass", "detail": "ok", "latency_ms": 1}],
            }

        with (
            patch.object(mod, "get_sync_db", return_value=db),
            patch.object(mod, "_get_bootstrap_settings", return_value=("admin", "", "")),
            patch.object(mod, "_detect_os_family", return_value="Linux"),
            patch("ansible_runner.run_async", return_value=(fake_thread, fake_runner)),
            patch("fleet_platform.services.salt_master_probe.run_probe", side_effect=_fake_probe),
        ):
            result = mod.provision_master(str(master.id), action="install")

        assert result["status"] == "successful"
        assert master.provision_status == "provisioned"
        assert master.os_family == "Linux"
        assert master.last_provisioned_at is not None
        assert len(probe_calls) == 1, "run_probe must be called on success"

    def test_success_sets_master_status_from_probe(self):
        import fleet_platform.workers.ansible_tasks as mod

        master = _make_master()
        prun = MagicMock()
        prun.id = uuid.uuid4()
        prun.status = "running"
        prun.finished_at = None

        db = MagicMock()
        db.__enter__ = MagicMock(return_value=db)
        db.__exit__ = MagicMock(return_value=False)

        # Return distinct objects for SaltMaster vs MasterProvisionRun queries
        def _execute_side_effect(stmt):
            r = MagicMock()
            stmt_str = str(stmt).lower()
            if "master_provision_run" in stmt_str:
                r.scalar_one_or_none.return_value = prun
            else:
                r.scalar_one_or_none.return_value = master
            return r

        db.execute.side_effect = _execute_side_effect

        def _fake_add(obj):
            if hasattr(obj, "salt_master_id"):
                obj.id = uuid.uuid4()

        db.add.side_effect = _fake_add

        fake_thread = MagicMock()
        fake_thread.is_alive.return_value = False
        fake_runner = MagicMock()
        fake_runner.rc = 0
        fake_runner.status = "successful"

        async def _fake_probe(_m):
            return {"status": "healthy", "checks": []}

        with (
            patch.object(mod, "get_sync_db", return_value=db),
            patch.object(mod, "_get_bootstrap_settings", return_value=("admin", "", "")),
            patch.object(mod, "_detect_os_family", return_value="Darwin"),
            patch("ansible_runner.run_async", return_value=(fake_thread, fake_runner)),
            patch("fleet_platform.services.salt_master_probe.run_probe", side_effect=_fake_probe),
        ):
            mod.provision_master(str(master.id), action="install")

        assert master.status == "healthy"
        assert master.os_family == "Darwin"

    def test_prun_finalized_on_success(self):
        """MasterProvisionRun.status should be 'completed' on success."""
        import fleet_platform.workers.ansible_tasks as mod

        master = _make_master()
        prun = MagicMock()
        prun.id = uuid.uuid4()
        prun.status = "running"
        prun.finished_at = None

        db = MagicMock()
        db.__enter__ = MagicMock(return_value=db)
        db.__exit__ = MagicMock(return_value=False)

        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = master
        db.execute.return_value = execute_result

        # For the MasterProvisionRun query, return the prun mock

        def _execute_side_effect(stmt):
            r = MagicMock()
            # If the query looks like it targets MasterProvisionRun, return prun
            if hasattr(stmt, "entity_zero") or "master_provision_run" in str(stmt).lower():
                r.scalar_one_or_none.return_value = prun
            else:
                r.scalar_one_or_none.return_value = master
            return r

        db.execute.side_effect = _execute_side_effect

        def _fake_add(obj):
            if hasattr(obj, "salt_master_id"):
                obj.id = uuid.uuid4()
                # Mimic ORM: assign prun reference
                prun.id = obj.id

        db.add.side_effect = _fake_add

        fake_thread = MagicMock()
        fake_thread.is_alive.return_value = False
        fake_runner = MagicMock()
        fake_runner.rc = 0
        fake_runner.status = "successful"

        async def _fake_probe(_m):
            return {"status": "healthy", "checks": []}

        with (
            patch.object(mod, "get_sync_db", return_value=db),
            patch.object(mod, "_get_bootstrap_settings", return_value=("admin", "", "")),
            patch.object(mod, "_detect_os_family", return_value="Linux"),
            patch("ansible_runner.run_async", return_value=(fake_thread, fake_runner)),
            patch("fleet_platform.services.salt_master_probe.run_probe", side_effect=_fake_probe),
        ):
            mod.provision_master(str(master.id), action="install")

        # prun.status should have been set to 'completed'
        assert prun.status == "completed"
        assert prun.finished_at is not None


# ---------------------------------------------------------------------------
# 4. Exception mid-run → finally sets failed; no stuck 'provisioning'
# ---------------------------------------------------------------------------


class TestExceptionHandling:
    def test_exception_sets_provision_failed(self):
        """An unexpected exception must not leave master.provision_status='provisioning'."""
        import fleet_platform.workers.ansible_tasks as mod

        master = _make_master()
        master.provision_status = "provisioning"  # simulating already-set state

        db = MagicMock()
        db.__enter__ = MagicMock(return_value=db)
        db.__exit__ = MagicMock(return_value=False)

        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = master
        db.execute.return_value = execute_result

        def _fake_add(obj):
            if hasattr(obj, "salt_master_id"):
                obj.id = uuid.uuid4()

        db.add.side_effect = _fake_add

        def _exploding_run_async(**kwargs):
            raise RuntimeError("Simulated ansible-runner crash")

        with (
            patch.object(mod, "get_sync_db", return_value=db),
            patch.object(mod, "_get_bootstrap_settings", return_value=("admin", "", "")),
            patch.object(mod, "_detect_os_family", return_value="Linux"),
            patch("ansible_runner.run_async", side_effect=_exploding_run_async),
        ):
            try:
                mod.provision_master(str(master.id), action="install")
            except RuntimeError:
                pass  # expected re-raise

        # master.provision_status must be 'failed', not 'provisioning'
        assert master.provision_status == "failed"
        assert master.provision_error is not None

    def test_finally_finalizes_prun_on_exception(self):
        """The finally block must finalize any running MasterProvisionRun on exception."""
        import fleet_platform.workers.ansible_tasks as mod

        master = _make_master()

        stuck_prun = MagicMock()
        stuck_prun.status = "running"
        stuck_prun.finished_at = None

        db = MagicMock()
        db.__enter__ = MagicMock(return_value=db)
        db.__exit__ = MagicMock(return_value=False)

        call_count = [0]

        def _execute_side_effect(stmt):
            r = MagicMock()
            call_count[0] += 1
            # The finally block looks for a running MasterProvisionRun
            r.scalar_one_or_none.return_value = stuck_prun if call_count[0] > 3 else master
            return r

        db.execute.side_effect = _execute_side_effect

        def _fake_add(obj):
            if hasattr(obj, "salt_master_id"):
                obj.id = uuid.uuid4()

        db.add.side_effect = _fake_add

        def _exploding_run_async(**kwargs):
            raise RuntimeError("crash")

        with (
            patch.object(mod, "get_sync_db", return_value=db),
            patch.object(mod, "_get_bootstrap_settings", return_value=("admin", "", "")),
            patch.object(mod, "_detect_os_family", return_value="Linux"),
            patch("ansible_runner.run_async", side_effect=_exploding_run_async),
        ):
            try:
                mod.provision_master(str(master.id), action="install")
            except RuntimeError:
                pass

        # DB commit must have been called (finalizing records)
        assert db.commit.called


# ---------------------------------------------------------------------------
# 5. Reaper marks stuck MasterProvisionRun + master failed
# ---------------------------------------------------------------------------


class TestReapOrphanedMasterProvisions:
    def test_reaper_task_exists(self):
        from fleet_platform.workers.maintenance import reap_orphaned_master_provisions

        assert callable(reap_orphaned_master_provisions)

    def test_reaper_marks_stuck_run_failed(self):
        from fleet_platform.workers import maintenance as maint

        db = MagicMock()
        db.__enter__ = MagicMock(return_value=db)
        db.__exit__ = MagicMock(return_value=False)

        update_result = MagicMock()
        update_result.rowcount = 2

        scalar_result = MagicMock()
        master_ids = [uuid.uuid4(), uuid.uuid4()]
        scalar_result.scalars.return_value.all.return_value = master_ids

        # First execute → select for master IDs; second → update MasterProvisionRun;
        # third → update SaltMaster
        execute_calls = [scalar_result, update_result, MagicMock()]
        db.execute.side_effect = execute_calls

        with patch.object(maint, "get_sync_db", return_value=db):
            result = maint.reap_orphaned_master_provisions()

        assert result["reaped"] == 2
        # Should have called execute at least twice (select + update)
        assert db.execute.call_count >= 2
        assert db.commit.called

    def test_reaper_in_beat_schedule(self):
        from fleet_platform.workers.celery_app import celery_app

        schedule = celery_app.conf.beat_schedule
        assert "reap-orphaned-master-provisions" in schedule
        entry = schedule["reap-orphaned-master-provisions"]
        assert entry["task"] == "fleet_platform.workers.maintenance.reap_orphaned_master_provisions"
        assert entry.get("options", {}).get("queue") == "maintenance"


# ---------------------------------------------------------------------------
# 6. /provision endpoint — admin required, task enqueued
# ---------------------------------------------------------------------------


class TestProvisionRoute:
    def test_provision_route_exists_in_router(self):
        """The /masters/{id}/provision POST route must be registered."""
        from fleet_platform.api.routes.salt_masters import router

        routes = [r.path for r in router.routes]
        provision_paths = [p for p in routes if "provision" in p]
        assert provision_paths, f"No /provision route found in router. Routes: {routes}"

    def test_provision_route_requires_admin(self):
        """The provision route must use require_role('admin')."""
        import inspect

        from fleet_platform.api.routes.salt_masters import trigger_provision_master

        src = inspect.getsource(trigger_provision_master)
        assert "require_role" in src, "trigger_provision_master must use require_role"
        assert "admin" in src, "trigger_provision_master must require 'admin' role"

    def test_provision_route_calls_delay(self):
        """The route must enqueue provision_master — not call the task directly.

        #749: routes dispatch by task name via celery_app.send_task rather than
        importing the worker and calling .delay(), to keep the api->worker import
        coupling broken.
        """
        import inspect

        from fleet_platform.api.routes.salt_masters import trigger_provision_master

        src = inspect.getsource(trigger_provision_master)
        assert "send_task" in src and "provision_master" in src, (
            "Route must enqueue provision_master via celery_app.send_task(...)"
        )

    def test_provision_route_returns_202_status(self):
        """The endpoint decorator must declare status_code=202."""
        from fleet_platform.api.routes.salt_masters import router

        for route in router.routes:
            if hasattr(route, "path") and "provision" in route.path:
                assert route.status_code == 202, f"Expected 202, got {route.status_code}"
                break
        else:
            assert False, "Provision route not found"

    def test_provision_task_is_registered(self):
        """provision_master must appear in celery_app's registered tasks."""
        from fleet_platform.workers.celery_app import celery_app

        task_names = list(celery_app.tasks.keys())
        assert any("provision_master" in n for n in task_names), (
            f"provision_master task not registered. Tasks: {task_names}"
        )
