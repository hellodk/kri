"""Unit tests for auto-resolved playbook credentials + source banner (#279, #349)."""

import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch


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


def _make_node(ssh_host_key=None):
    """Build a minimal Node-like stub for credential resolver tests.

    As of #989 (GROUP-ONLY contract) a node carries no credential state of its
    own — only ``ssh_host_key`` (controller-key tier) and group membership
    (mocked at the DB layer via the credential_groups tier).
    """
    node = MagicMock()
    node.id = 1
    node.minion_id = "node-01"
    node.ssh_host_key = ssh_host_key
    return node


def _make_db_no_group_no_global():
    """Sync DB stub: no credential_groups mapping, no platform settings."""
    db = MagicMock()
    # scalar_one_or_none() returns None for the platform setting query
    db.execute.return_value.scalar_one_or_none.return_value = None
    # first() returns None for the credential_groups tier (same fixed
    # return_value mock is reused across every db.execute() call here).
    db.execute.return_value.first.return_value = None
    return db


# ---------------------------------------------------------------------------
# Controller-key tier (sync resolver) — #349 last acceptance criterion
# ---------------------------------------------------------------------------


def test_sync_resolver_bootstrapped_node_uses_controller_key(tmp_path):
    """Bootstrapped node (ssh_host_key set), no explicit creds → controller key tier."""
    from fleet_platform.services.credential_resolver import resolve_node_credentials_sync

    key_content = "fake-controller-key-material-for-tests\n"
    node = _make_node(ssh_host_key="ecdsa-sha2-nistp256 AAAA...")
    db = _make_db_no_group_no_global()

    with patch(
        "fleet_platform.services.credential_resolver._read_controller_key",
        return_value=key_content,
    ):
        result = resolve_node_credentials_sync(node, db)

    assert result["auth_mode"] == "key"
    assert result["credential_source"] == "controller"
    assert result["ssh_key"] == key_content
    assert result["ssh_password"] == ""


def test_sync_resolver_bootstrapped_node_key_missing_falls_to_none(tmp_path):
    """Bootstrapped node but controller key file absent → falls through to the
    credential-less 'none' tier (no global password fallback, #989)."""
    from fleet_platform.services.credential_resolver import resolve_node_credentials_sync

    node = _make_node(ssh_host_key="ecdsa-sha2-nistp256 AAAA...")
    db = _make_db_no_group_no_global()

    with patch(
        "fleet_platform.services.credential_resolver._read_controller_key",
        return_value="",
    ):
        result = resolve_node_credentials_sync(node, db)

    assert result["credential_source"] == "none"


def test_sync_resolver_bootstrapped_node_with_credential_group_wins_over_controller():
    """Node with ssh_host_key set AND a usable credential_groups credential → the
    group credential wins over the controller key tier (#989: credential_groups
    is the only per-node/group secret source, and it is tried first)."""
    from fleet_platform.services.credential_resolver import resolve_node_credentials_sync
    from fleet_platform.services.platform_settings_svc import encrypt_secret

    cred = MagicMock()
    cred.id = uuid.uuid4()
    cred.kind = "username_password"
    cred.username = "ops"
    cred.secret_enc = encrypt_secret("ops-pw")
    cred.last_used_at = None

    node = _make_node(ssh_host_key="ecdsa-sha2-nistp256 AAAA...")
    db = MagicMock()
    cg_result = MagicMock()
    cg_result.first.return_value = (cred, "prod")
    db.execute.return_value = cg_result

    with patch(
        "fleet_platform.services.credential_resolver._read_controller_key",
        return_value="SHOULD_NOT_BE_USED",
    ):
        result = resolve_node_credentials_sync(node, db)

    assert result["credential_source"] == "group:prod"
    assert result["ssh_user"] == "ops"
    assert result["ssh_password"] == "ops-pw"


def test_sync_resolver_non_bootstrapped_node_uses_none_tier():
    """Node without ssh_host_key (never bootstrapped) → skips controller tier →
    credential-less 'none' tier."""
    from fleet_platform.services.credential_resolver import resolve_node_credentials_sync

    node = _make_node(ssh_host_key=None)
    db = _make_db_no_group_no_global()

    with patch(
        "fleet_platform.services.credential_resolver._read_controller_key",
        return_value="SHOULD_NOT_BE_CALLED",
    ) as mock_ck:
        result = resolve_node_credentials_sync(node, db)

    assert result["credential_source"] == "none"
    mock_ck.assert_not_called()


# ---------------------------------------------------------------------------
# Controller-key tier (async resolver) — #349 last acceptance criterion
# ---------------------------------------------------------------------------


def test_async_resolver_bootstrapped_node_uses_controller_key():
    """Async resolver: bootstrapped node, no explicit creds → controller key tier."""
    import asyncio

    from fleet_platform.services.credential_resolver import resolve_node_credentials

    key_content = "fake-controller-key-material-for-tests\n"
    node = _make_node(ssh_host_key="ecdsa-sha2-nistp256 AAAA...")

    async def _run():
        # Async DB: group query returns None, global setting returns ""
        db = MagicMock()
        db.execute = MagicMock()

        async def _fake_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            result.first.return_value = None  # #984 credential_groups tier
            return result

        db.execute.side_effect = _fake_execute

        with patch(
            "fleet_platform.services.credential_resolver._read_controller_key",
            return_value=key_content,
        ):
            return await resolve_node_credentials(node, db)

    result = asyncio.run(_run())
    assert result["auth_mode"] == "key"
    assert result["credential_source"] == "controller"
    assert result["ssh_key"] == key_content
    assert result["ssh_password"] == ""


def test_async_resolver_bootstrapped_node_key_missing_falls_to_none():
    """Async resolver: bootstrapped node but key absent → credential-less 'none' tier."""
    import asyncio

    from fleet_platform.services.credential_resolver import resolve_node_credentials

    node = _make_node(ssh_host_key="ecdsa-sha2-nistp256 AAAA...")

    async def _run():
        db = MagicMock()

        async def _fake_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            result.first.return_value = None  # #984 credential_groups tier
            return result

        db.execute.side_effect = _fake_execute

        with patch(
            "fleet_platform.services.credential_resolver._read_controller_key",
            return_value="",
        ):
            return await resolve_node_credentials(node, db)

    result = asyncio.run(_run())
    assert result["credential_source"] == "none"


def test_inventory_writes_per_host_user_and_password():
    """Password hosts must appear in inventory.ini (user/host) and have host_vars files (#349).

    ansible_ssh_pass must NOT be inlined into inventory.ini — it goes into
    host_vars/{alias}.yml (mode 0600) to prevent leakage into ansible -vvv logs
    and artifact files.
    """
    from fleet_platform.workers.playbook_tasks import _write_static_inventory

    with tempfile.TemporaryDirectory() as tmp:
        hosts = [
            _host("web01", "10.0.0.5", "admin", ssh_password="pw1", source="group:prod"),
            _host("db01", "10.0.0.9", "root", ssh_password="pw2", source="node"),
        ]
        inv_path = _write_static_inventory(tmp, hosts)
        content = Path(inv_path).read_text()
        # Passwords must NOT appear inline in inventory.ini (#349)
        assert "ansible_ssh_pass" not in content, "passwords must not be inlined in inventory.ini"
        assert "web01 ansible_host=10.0.0.5 ansible_user=admin" in content
        assert "db01 ansible_host=10.0.0.9 ansible_user=root" in content
        # Passwords must be written to per-host host_vars files (check inside with-block)
        hv_web01 = Path(tmp) / "host_vars" / "web01.yml"
        hv_db01 = Path(tmp) / "host_vars" / "db01.yml"
        assert hv_web01.exists(), "host_vars/web01.yml must exist for password host"
        assert hv_db01.exists(), "host_vars/db01.yml must exist for password host"
        assert "pw1" in hv_web01.read_text()
        assert "pw2" in hv_db01.read_text()


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
