"""Tests for #354: TOFU host-key verification in run_playbook.

ansible.cfg ships StrictHostKeyChecking=no (MITM-able forever).  The worker
must override that via ANSIBLE_SSH_ARGS env before calling run_async, using each
node's stored ssh_host_key for strict verification when available.

TDD: write tests first, make them red, then implement.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helper: build a minimal host dict (mirrors _host_entry output)
# ---------------------------------------------------------------------------


def _host(
    hostname: str,
    ip: str,
    ssh_user: str = "admin",
    ssh_password: str = "",
    ssh_key: str = "",
    auth_mode: str = "password",
    source: str = "node",
    ssh_host_key: str = "",
) -> dict:
    return {
        "hostname": hostname,
        "ip": ip,
        "ssh_user": ssh_user,
        "ssh_password": ssh_password,
        "ssh_key": ssh_key,
        "auth_mode": auth_mode,
        "credential_source": source,
        "ssh_host_key": ssh_host_key,
    }


# ---------------------------------------------------------------------------
# _write_known_hosts: unit tests
# ---------------------------------------------------------------------------


def test_write_known_hosts_all_keyed_writes_correct_lines():
    """All hosts have keys → file contains '{ip} {key}' lines, all_have_keys=True."""
    from fleet_platform.workers.playbook_tasks import _write_known_hosts

    hosts = [
        _host("mac-01", "10.0.0.1", ssh_host_key="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIkey1"),
        _host("mac-02", "10.0.0.2", ssh_host_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCkey2"),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        kh_path, all_have_keys = _write_known_hosts(tmpdir, hosts)

        assert all_have_keys is True
        content = Path(kh_path).read_text()
        assert "10.0.0.1 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIkey1" in content
        assert "10.0.0.2 ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCkey2" in content


def test_write_known_hosts_file_is_0600():
    """known_hosts file must be mode 0600."""
    from fleet_platform.workers.playbook_tasks import _write_known_hosts

    hosts = [_host("mac-01", "10.0.0.1", ssh_host_key="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIkey1")]
    with tempfile.TemporaryDirectory() as tmpdir:
        kh_path, _ = _write_known_hosts(tmpdir, hosts)
        mode = Path(kh_path).stat().st_mode & 0o777
        assert mode == 0o600, f"known_hosts must be 0600, got {oct(mode)}"


def test_write_known_hosts_mixed_keys_returns_false():
    """At least one host without a key → all_have_keys=False (accept-new mode)."""
    from fleet_platform.workers.playbook_tasks import _write_known_hosts

    hosts = [
        _host("mac-01", "10.0.0.1", ssh_host_key="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIkey1"),
        _host("mac-02", "10.0.0.2", ssh_host_key=""),  # no key
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        kh_path, all_have_keys = _write_known_hosts(tmpdir, hosts)

        assert all_have_keys is False
        content = Path(kh_path).read_text()
        # The keyed host must still be present
        assert "10.0.0.1 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIkey1" in content
        # The keyless host must NOT be present
        assert "10.0.0.2" not in content


def test_write_known_hosts_empty_key_skipped():
    """Hosts with empty or whitespace-only ssh_host_key are skipped in the file."""
    from fleet_platform.workers.playbook_tasks import _write_known_hosts

    hosts = [
        _host("mac-01", "10.0.0.1", ssh_host_key=""),
        _host("mac-02", "10.0.0.2", ssh_host_key="   "),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        kh_path, all_have_keys = _write_known_hosts(tmpdir, hosts)

        assert all_have_keys is False
        content = Path(kh_path).read_text()
        assert "10.0.0.1" not in content
        assert "10.0.0.2" not in content


def test_write_known_hosts_all_empty_creates_empty_file():
    """Even with no keyed hosts, known_hosts file must exist (0600) and be empty."""
    from fleet_platform.workers.playbook_tasks import _write_known_hosts

    hosts = [_host("mac-01", "10.0.0.1", ssh_host_key="")]
    with tempfile.TemporaryDirectory() as tmpdir:
        kh_path, all_have_keys = _write_known_hosts(tmpdir, hosts)

        assert all_have_keys is False
        assert Path(kh_path).exists(), "known_hosts file must be created even when empty"
        assert Path(kh_path).read_text().strip() == ""


def test_write_known_hosts_no_hosts_creates_empty_file():
    """Empty host list → empty file, all_have_keys=False."""
    from fleet_platform.workers.playbook_tasks import _write_known_hosts

    with tempfile.TemporaryDirectory() as tmpdir:
        kh_path, all_have_keys = _write_known_hosts(tmpdir, [])

        assert all_have_keys is False
        assert Path(kh_path).exists()
        assert Path(kh_path).read_text().strip() == ""


# ---------------------------------------------------------------------------
# _host_entry: must include ssh_host_key
# ---------------------------------------------------------------------------


def test_host_entry_includes_ssh_host_key():
    """_host_entry must include 'ssh_host_key' from node.ssh_host_key."""
    from fleet_platform.workers.playbook_tasks import _host_entry

    node = MagicMock()
    node.hostname = "mac-01"
    node.ip_address = "10.0.0.1"
    node.ssh_host_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIkey1"

    db = MagicMock()
    mock_creds = {
        "ssh_user": "admin",
        "ssh_password": "",
        "ssh_key": "",
        "auth_mode": "password",
        "credential_source": "node",
    }
    with patch("fleet_platform.workers.playbook_tasks.resolve_node_credentials_sync", return_value=mock_creds):
        entry = _host_entry(node, db, override=None)

    assert "ssh_host_key" in entry, "'ssh_host_key' must be present in _host_entry dict"
    assert entry["ssh_host_key"] == "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIkey1"


def test_host_entry_ssh_host_key_defaults_to_empty_string():
    """_host_entry must return ssh_host_key='' when node.ssh_host_key is None."""
    from fleet_platform.workers.playbook_tasks import _host_entry

    node = MagicMock()
    node.hostname = "mac-01"
    node.ip_address = "10.0.0.1"
    node.ssh_host_key = None

    db = MagicMock()
    mock_creds = {
        "ssh_user": "admin",
        "ssh_password": "",
        "ssh_key": "",
        "auth_mode": "password",
        "credential_source": "node",
    }
    with patch("fleet_platform.workers.playbook_tasks.resolve_node_credentials_sync", return_value=mock_creds):
        entry = _host_entry(node, db, override=None)

    assert "ssh_host_key" in entry
    assert entry["ssh_host_key"] == ""


def test_host_entry_manual_override_includes_empty_ssh_host_key():
    """_host_entry with manual override must still include ssh_host_key (empty when override has no key)."""
    from fleet_platform.workers.playbook_tasks import _host_entry

    node = MagicMock()
    node.hostname = "mac-01"
    node.ip_address = "10.0.0.1"
    node.ssh_host_key = None

    db = MagicMock()
    override = {"ssh_user": "ops", "ssh_password": "pass"}
    entry = _host_entry(node, db, override=override)

    assert "ssh_host_key" in entry
    assert entry["ssh_host_key"] == ""


# ---------------------------------------------------------------------------
# MITM semantics: mode mapping
# ---------------------------------------------------------------------------


def test_mode_is_yes_when_all_hosts_have_keys():
    """StrictHostKeyChecking=yes when all hosts have stored keys (full verification)."""
    from fleet_platform.workers.playbook_tasks import _write_known_hosts

    hosts = [
        _host("mac-01", "10.0.0.1", ssh_host_key="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIkey1"),
        _host("mac-02", "10.0.0.2", ssh_host_key="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIkey2"),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        _, all_have_keys = _write_known_hosts(tmpdir, hosts)

    mode = "yes" if all_have_keys else "accept-new"
    assert mode == "yes", "all keyed hosts must produce StrictHostKeyChecking=yes"


def test_mode_is_accept_new_when_any_host_lacks_key():
    """StrictHostKeyChecking=accept-new when any host is missing a stored key."""
    from fleet_platform.workers.playbook_tasks import _write_known_hosts

    hosts = [
        _host("mac-01", "10.0.0.1", ssh_host_key="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIkey1"),
        _host("mac-02", "10.0.0.2", ssh_host_key=""),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        _, all_have_keys = _write_known_hosts(tmpdir, hosts)

    mode = "yes" if all_have_keys else "accept-new"
    assert mode == "accept-new", "mixed keyed/unkeyed hosts must produce StrictHostKeyChecking=accept-new"


# ---------------------------------------------------------------------------
# Source-contract: ANSIBLE_SSH_ARGS override present in run_playbook source
# ---------------------------------------------------------------------------


def test_ansible_ssh_args_env_override_present_in_source():
    """run_playbook source must set ANSIBLE_SSH_ARGS with UserKnownHostsFile and StrictHostKeyChecking."""
    module_path = Path(__file__).parent.parent.parent / "fleet_platform" / "workers" / "playbook_tasks.py"
    source = module_path.read_text()

    assert "ANSIBLE_SSH_ARGS" in source, "playbook_tasks.py must set ANSIBLE_SSH_ARGS env override"
    assert "UserKnownHostsFile" in source, "ANSIBLE_SSH_ARGS must include UserKnownHostsFile reference"
    assert "StrictHostKeyChecking" in source, "ANSIBLE_SSH_ARGS must include StrictHostKeyChecking reference"


def test_ssh_host_key_in_host_entry_source():
    """playbook_tasks.py source must reference 'ssh_host_key' in _host_entry."""
    module_path = Path(__file__).parent.parent.parent / "fleet_platform" / "workers" / "playbook_tasks.py"
    source = module_path.read_text()

    assert "ssh_host_key" in source, "playbook_tasks.py must reference ssh_host_key in _host_entry"


def test_write_known_hosts_referenced_in_source():
    """playbook_tasks.py source must define and call _write_known_hosts."""
    module_path = Path(__file__).parent.parent.parent / "fleet_platform" / "workers" / "playbook_tasks.py"
    source = module_path.read_text()

    assert "_write_known_hosts" in source, "playbook_tasks.py must define/call _write_known_hosts"
