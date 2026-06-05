# tests/unit/test_playbook_tasks.py
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch


def _host(hostname, ip, user, password="", source="node"):
    return {
        "hostname": hostname,
        "ip": ip,
        "ssh_user": user,
        "ssh_password": password,
        "ssh_key": "",
        "auth_mode": "password",
        "credential_source": source,
    }


def test_write_static_inventory_single_host(tmp_path):
    from fleet_platform.workers.playbook_tasks import _write_static_inventory

    inv_path = _write_static_inventory(str(tmp_path), [_host("mac-01", "10.0.1.11", "admin")])
    content = Path(inv_path).read_text()
    assert "[targets]" in content
    assert "mac-01 ansible_host=10.0.1.11 ansible_user=admin" in content


def test_write_static_inventory_multiple_hosts(tmp_path):
    from fleet_platform.workers.playbook_tasks import _write_static_inventory

    hosts = [_host("mac-01", "10.0.1.11", "admin"), _host("mac-02", "10.0.1.12", "admin")]
    inv_path = _write_static_inventory(str(tmp_path), hosts)
    content = Path(inv_path).read_text()
    assert "mac-01 ansible_host=10.0.1.11" in content
    assert "mac-02 ansible_host=10.0.1.12" in content


def test_write_var_file_creates_yaml(tmp_path):
    from fleet_platform.workers.playbook_tasks import _write_var_file

    _write_var_file(tmp_path / "host_vars" / "mac-01.yml", {"log_level": "debug", "timeout": 30})
    content = (tmp_path / "host_vars" / "mac-01.yml").read_text()
    assert "log_level: debug" in content
    assert "timeout: 30" in content


def test_run_playbook_missing_job_returns_early():
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalar_one_or_none.return_value = None

    with patch("fleet_platform.workers.playbook_tasks.get_sync_db", return_value=mock_db):
        from fleet_platform.workers.playbook_tasks import run_playbook

        result = run_playbook(str(uuid.uuid4()))
    assert result["status"] == "error"
    assert result["reason"] == "job_not_found"
