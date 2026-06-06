"""Tests for #349: ansible_ssh_pass must never appear inline in inventory.ini.

Password hosts must write host_vars/{alias}.yml (mode 0600) instead.
"""

import json
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


# ---------------------------------------------------------------------------
# Core invariant: no plaintext pass in inventory.ini
# ---------------------------------------------------------------------------


def test_password_host_inventory_does_not_contain_ansible_ssh_pass():
    """ansible_ssh_pass must NOT appear inline in inventory.ini for password hosts."""
    from fleet_platform.workers.playbook_tasks import _write_static_inventory

    with tempfile.TemporaryDirectory() as tmp:
        hosts = [_host("web01", "10.0.0.5", "admin", ssh_password="s3cr3t", source="node")]
        inv_path = _write_static_inventory(tmp, hosts)
        content = Path(inv_path).read_text()

    assert "ansible_ssh_pass" not in content, (
        "ansible_ssh_pass must not appear inline in inventory.ini — use host_vars/{alias}.yml"
    )
    assert "s3cr3t" not in content, "raw password must not appear anywhere in inventory.ini"


# ---------------------------------------------------------------------------
# host_vars file: existence, mode, content
# ---------------------------------------------------------------------------


def test_password_host_vars_file_exists_and_is_0600():
    """host_vars/{alias}.yml must be written for password hosts and be mode 0600."""
    from fleet_platform.workers.playbook_tasks import _write_static_inventory

    with tempfile.TemporaryDirectory() as tmp:
        hosts = [_host("web01", "10.0.0.5", "admin", ssh_password="s3cr3t", source="node")]
        _write_static_inventory(tmp, hosts)

        hv_file = Path(tmp) / "host_vars" / "web01.yml"
        assert hv_file.exists(), "host_vars/web01.yml must be created for a password host"

        mode = hv_file.stat().st_mode & 0o777
        assert mode == 0o600, f"host_vars file must be 0600, got {oct(mode)}"


def test_password_host_vars_file_contains_password():
    """host_vars/{alias}.yml must contain ansible_ssh_pass with the correct password value."""
    from fleet_platform.workers.playbook_tasks import _write_static_inventory

    with tempfile.TemporaryDirectory() as tmp:
        hosts = [_host("web01", "10.0.0.5", "admin", ssh_password="s3cr3t", source="node")]
        _write_static_inventory(tmp, hosts)

        hv_file = Path(tmp) / "host_vars" / "web01.yml"
        content = hv_file.read_text()

    # Content should be YAML: ansible_ssh_pass: "s3cr3t"
    assert "ansible_ssh_pass" in content
    # The value must be json-quoted (a JSON string is a valid YAML scalar)
    assert json.dumps("s3cr3t") in content, "password must be json-quoted in the YAML file"


# ---------------------------------------------------------------------------
# Key-auth hosts: unchanged behaviour
# ---------------------------------------------------------------------------


def test_key_auth_host_writes_key_file_and_not_host_vars():
    """Key-auth hosts must write the private key file and NO host_vars file."""
    from fleet_platform.workers.playbook_tasks import _write_static_inventory

    with tempfile.TemporaryDirectory() as tmp:
        hosts = [_host("k01", "10.0.0.1", "admin", ssh_key="PRIVKEY\n", auth_mode="key", source="node")]
        inv_path = _write_static_inventory(tmp, hosts)
        content = Path(inv_path).read_text()

        hv_dir = Path(tmp) / "host_vars"
        hv_file = hv_dir / "k01.yml"

    assert "ansible_ssh_private_key_file=" in content, "key-auth host must have private key file reference"
    assert "ansible_ssh_pass" not in content, "key-auth host must not have password in inventory"
    assert not hv_file.exists(), "key-auth host must not produce a host_vars file"


def test_key_auth_key_file_is_0600():
    """Private key file for key-auth host must be mode 0600."""
    from fleet_platform.workers.playbook_tasks import _write_static_inventory

    with tempfile.TemporaryDirectory() as tmp:
        hosts = [_host("k01", "10.0.0.1", "admin", ssh_key="PRIVKEY", auth_mode="key", source="node")]
        _write_static_inventory(tmp, hosts)

        key_files = list(Path(tmp).glob("*.key"))
        assert key_files, "a .key file must be written for key-auth host"
        for kf in key_files:
            mode = kf.stat().st_mode & 0o777
            assert mode == 0o600, f"key file {kf} must be 0600, got {oct(mode)}"


# ---------------------------------------------------------------------------
# Path-traversal: alias and filename sanitisation
# ---------------------------------------------------------------------------


def test_unsafe_hostname_alias_and_filename_are_sanitised():
    """Hostname with unsafe chars must produce a sanitised alias and filename — no path traversal."""
    from fleet_platform.workers.playbook_tasks import _write_static_inventory

    evil_hostname = "evil/../host"

    with tempfile.TemporaryDirectory() as tmp:
        hosts = [_host(evil_hostname, "10.0.0.99", "admin", ssh_password="pw", source="node")]
        inv_path = _write_static_inventory(tmp, hosts)
        content = Path(inv_path).read_text()
        hv_dir = Path(tmp) / "host_vars"

    # The raw hostname must NOT appear as the alias in inventory
    assert "evil/../host" not in content, "unsanitised path-traversal hostname must not appear in inventory"

    # The host_vars file must exist inside tmpdir (no escape)
    if hv_dir.exists():
        for f in hv_dir.iterdir():
            resolved = f.resolve()
            tmp_resolved = Path(tmp).resolve()
            assert str(resolved).startswith(str(tmp_resolved)), f"host_vars file {f} escaped tmpdir via path traversal"

    # The alias in inventory must be the sanitised form — verify the sanitised label matches
    from fleet_platform.workers.playbook_tasks import _safe_label

    safe = _safe_label(evil_hostname)
    assert safe in content, f"sanitised alias '{safe}' must appear in inventory, got:\n{content}"


def test_unsafe_hostname_alias_and_hv_filename_match():
    """Sanitised alias in inventory must exactly match the host_vars filename stem."""
    from fleet_platform.workers.playbook_tasks import _safe_label, _write_static_inventory

    evil_hostname = "evil/../host"
    safe = _safe_label(evil_hostname)

    with tempfile.TemporaryDirectory() as tmp:
        hosts = [_host(evil_hostname, "10.0.0.99", "admin", ssh_password="pw", source="node")]
        _write_static_inventory(tmp, hosts)
        hv_dir = Path(tmp) / "host_vars"
        hv_file = hv_dir / f"{safe}.yml"
        assert hv_file.exists(), f"host_vars file must be named after sanitised alias '{safe}', not the raw hostname"


# ---------------------------------------------------------------------------
# Inventory file itself is 0600
# ---------------------------------------------------------------------------


def test_inventory_file_is_0600():
    """inventory.ini must be mode 0600."""
    from fleet_platform.workers.playbook_tasks import _write_static_inventory

    with tempfile.TemporaryDirectory() as tmp:
        hosts = [_host("h", "1.2.3.4", "u", ssh_password="p")]
        inv_path = _write_static_inventory(tmp, hosts)
        mode = Path(inv_path).stat().st_mode & 0o077

    assert mode == 0, "inventory.ini must not be group/other readable"


# ---------------------------------------------------------------------------
# Source-contract test: the inline f-string form must be gone from source
# ---------------------------------------------------------------------------


def test_ansible_ssh_pass_inline_not_in_module_source():
    """The literal 'ansible_ssh_pass=' f-string must not appear in playbook_tasks.py source."""
    module_path = Path(__file__).parent.parent.parent / "fleet_platform" / "workers" / "playbook_tasks.py"
    source = module_path.read_text()
    # The old inline form was: parts.append(f"ansible_ssh_pass={h['ssh_password']}")
    assert 'f"ansible_ssh_pass=' not in source, (
        "ansible_ssh_pass inline f-string must be removed — password goes in host_vars/{alias}.yml"
    )
