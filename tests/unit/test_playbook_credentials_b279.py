"""Unit tests for auto-resolved playbook credentials + source banner (#279)."""
import tempfile
from pathlib import Path


def _host(hostname, ip, ssh_user, ssh_password="", ssh_key="", auth_mode="password", source="node"):
    return {
        "hostname": hostname,
        "ip": ip,
        "ssh_user": ssh_user,
        "ssh_password": ssh_password,
        "ssh_key": ssh_key,
        "auth_mode": auth_mode,
        "credential_source": source,
    }


def test_inventory_writes_per_host_user_and_password():
    from fleet_platform.workers.playbook_tasks import _write_static_inventory
    with tempfile.TemporaryDirectory() as tmp:
        hosts = [
            _host("web01", "10.0.0.5", "admin", ssh_password="pw1", source="group:prod"),
            _host("db01", "10.0.0.9", "root", ssh_password="pw2", source="node"),
        ]
        inv_path = _write_static_inventory(tmp, hosts)
        content = Path(inv_path).read_text()
    assert "web01 ansible_host=10.0.0.5 ansible_user=admin" in content
    assert "ansible_ssh_pass=pw1" in content
    assert "db01 ansible_host=10.0.0.9 ansible_user=root" in content
    assert "ansible_ssh_pass=pw2" in content


def test_inventory_key_auth_writes_key_file_not_password():
    from fleet_platform.workers.playbook_tasks import _write_static_inventory
    with tempfile.TemporaryDirectory() as tmp:
        hosts = [_host("k01", "10.0.0.1", "admin", ssh_key="PRIVKEY", auth_mode="key", source="node")]
        inv_path = _write_static_inventory(tmp, hosts)
        content = Path(inv_path).read_text()
    assert "ansible_ssh_private_key_file=" in content
    assert "ansible_ssh_pass" not in content
    # The key material is written to a 0600 file, never inline in the inventory
    assert "PRIVKEY" not in content


def test_inventory_file_is_not_world_readable():
    from fleet_platform.workers.playbook_tasks import _write_static_inventory
    with tempfile.TemporaryDirectory() as tmp:
        inv_path = _write_static_inventory(tmp, [_host("h", "1.2.3.4", "u", ssh_password="p")])
        mode = Path(inv_path).stat().st_mode & 0o077
    assert mode == 0, "inventory holds secrets and must not be group/other-readable"


def test_credential_source_banner_lists_each_host():
    from fleet_platform.workers.playbook_tasks import _credential_source_banner
    hosts = [
        _host("web01", "10.0.0.5", "admin", source="group:prod"),
        _host("db01", "10.0.0.9", "root", source="node"),
    ]
    banner = _credential_source_banner(hosts)
    assert "web01" in banner and "10.0.0.5" in banner and "group:prod" in banner
    assert "db01" in banner and "node" in banner
