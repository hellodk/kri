# tests/unit/test_salt_tasks.py
"""Unit tests for container runtime detection in salt_tasks."""
import logging
from unittest.mock import MagicMock, patch


def test_find_runtime_docker_on_path():
    """shutil.which finds docker — returns its path."""
    from fleet_platform.workers.salt_tasks import _find_runtime

    with patch("fleet_platform.workers.salt_tasks.shutil.which") as mock_which:
        mock_which.side_effect = lambda rt: "/usr/bin/docker" if rt == "docker" else None
        result = _find_runtime()

    assert result == "/usr/bin/docker"


def test_find_runtime_podman_when_docker_absent():
    """shutil.which finds podman after docker is not on PATH."""
    from fleet_platform.workers import salt_tasks

    with patch("fleet_platform.workers.salt_tasks.shutil.which") as mock_which, \
         patch.object(salt_tasks, "_EXTRA_PATHS", ()):
        mock_which.side_effect = lambda rt: "/usr/bin/podman" if rt == "podman" else None
        result = salt_tasks._find_runtime()

    assert result == "/usr/bin/podman"


def test_find_runtime_extra_path_fallback(tmp_path):
    """Falls back to extra paths when shutil.which returns None."""
    from fleet_platform.workers import salt_tasks

    fake_docker = tmp_path / "docker"
    fake_docker.write_text("#!/bin/sh\n")
    fake_docker.chmod(0o755)

    with patch("fleet_platform.workers.salt_tasks.shutil.which", return_value=None), \
         patch.object(salt_tasks, "_EXTRA_PATHS", (str(tmp_path),)):
        result = salt_tasks._find_runtime()

    assert result == str(fake_docker)


def test_find_runtime_missing():
    """Returns None when neither docker nor podman is found anywhere."""
    from fleet_platform.workers import salt_tasks

    with patch("fleet_platform.workers.salt_tasks.shutil.which", return_value=None), \
         patch.object(salt_tasks, "_EXTRA_PATHS", ("/nonexistent/path",)):
        result = salt_tasks._find_runtime()

    assert result is None


def test_salt_prefix_container_mode():
    """Returns [runtime, exec, container] when runtime is found."""
    from fleet_platform.workers import salt_tasks

    with patch.object(salt_tasks, "_SALT_MASTER_CONTAINER", "deploy-salt-master-1"), \
         patch.object(salt_tasks, "_find_runtime", return_value="/usr/bin/docker"):
        prefix = salt_tasks._salt_prefix()

    assert prefix == ["/usr/bin/docker", "exec", "deploy-salt-master-1"]


def test_salt_prefix_bare_metal_mode():
    """Returns empty list when SALT_MASTER_CONTAINER is empty."""
    from fleet_platform.workers import salt_tasks

    with patch.object(salt_tasks, "_SALT_MASTER_CONTAINER", ""):
        prefix = salt_tasks._salt_prefix()

    assert prefix == []


def test_salt_prefix_no_runtime_falls_back_to_bare_metal(caplog):
    """When container is set but no runtime found, falls back to bare-metal with a warning."""
    from fleet_platform.workers import salt_tasks

    with patch.object(salt_tasks, "_SALT_MASTER_CONTAINER", "deploy-salt-master-1"), \
         patch.object(salt_tasks, "_find_runtime", return_value=None), \
         caplog.at_level(logging.WARNING, logger="fleet_platform.workers.salt_tasks"):
        prefix = salt_tasks._salt_prefix()

    assert prefix == []
    assert "No container runtime" in caplog.text or "no container runtime" in caplog.text.lower()


def test_run_salt_cmd_rejects_disallowed_function():
    """run_salt_cmd returns error dict for functions not in the allowlist."""
    from fleet_platform.workers.salt_tasks import run_salt_cmd

    result = run_salt_cmd.run(function="cmd.exec", target_minions=["minion1"])
    assert result["status"] == "error"
    assert "allowlist" in result["reason"].lower()


def test_run_salt_cmd_allows_test_ping():
    """test.ping is in the allowlist and reaches subprocess."""
    from fleet_platform.workers import salt_tasks
    from fleet_platform.workers.salt_tasks import run_salt_cmd

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = '{"minion1": true}'
    mock_proc.stderr = ""

    with patch("fleet_platform.workers.salt_tasks.subprocess.run", return_value=mock_proc) as mock_run, \
         patch.object(salt_tasks, "_salt_prefix", return_value=[]):
        result = run_salt_cmd.run(function="test.ping", target_minions=["minion1"])

    assert result["status"] == "ok"
    called_cmd = mock_run.call_args[0][0]
    assert "test.ping" in called_cmd
