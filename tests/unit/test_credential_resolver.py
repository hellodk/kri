# tests/unit/test_credential_resolver.py
"""Unit tests for fleet_platform.services.credential_resolver.

As of #989 (Chunk 1 — GROUP-ONLY credential contract) the resolver has exactly
two tiers: the ``credential_groups`` association (a node's group membership)
and the controller key. There is no per-node credential, no legacy
``Group.credential_id`` column, and no global-password fallback — a node with
no usable secret in either tier resolves to ``credential_source: 'none'``.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.services.credential_resolver import (
    node_has_group,
    resolve_node_credentials,
)
from fleet_platform.services.platform_settings_svc import encrypt_secret

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Row:
    """Mimics a SQLAlchemy (Credential, group_name) Row consumed via ``.first()``."""

    def __init__(self, cred, name):
        self._t = (cred, name)

    def __iter__(self):
        return iter(self._t)


def _make_db(cg_result, *scalar_returns):
    """Build an AsyncMock db.

    ``cg_result`` is what the credential_groups tier's ``.first()`` call
    returns (a :class:`_Row` or ``None``). Any further ``scalar_returns`` are
    consumed in order via ``.scalar_one_or_none()`` by subsequent calls
    (e.g. the global SSH_USERNAME setting read).
    """
    db = AsyncMock(spec=AsyncSession)
    results = []

    r0 = MagicMock()
    r0.first.return_value = cg_result
    results.append(r0)

    for val in scalar_returns:
        r = MagicMock()
        r.scalar_one_or_none.return_value = val
        results.append(r)

    db.execute.side_effect = results
    return db


def _node(ssh_host_key=None):
    node = MagicMock()
    node.id = uuid.uuid4()
    node.minion_id = "node-01"
    node.ssh_host_key = ssh_host_key  # None = not bootstrapped
    return node


def _credential(kind="username_password", username="cuser", secret_plain="cpw"):
    cred = MagicMock()
    cred.id = uuid.uuid4()
    cred.kind = kind
    cred.username = username
    cred.secret_enc = encrypt_secret(secret_plain) if secret_plain is not None else ""
    cred.last_used_at = None
    return cred


def _platform_row(value, is_encrypted=False):
    row = MagicMock()
    row.value = value
    row.is_encrypted = is_encrypted
    return row


# ---------------------------------------------------------------------------
# credential_groups tier
# ---------------------------------------------------------------------------


async def test_credential_group_tier_password():
    """Group credential (via credential_groups) resolves to password auth, source 'group:<name>'."""
    cred = _credential(kind="username_password", username="cguser", secret_plain="cgpw")
    node = _node()
    db = _make_db(_Row(cred, "prod"))

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "group:prod"
    assert result["ssh_user"] == "cguser"
    assert result["ssh_password"] == "cgpw"
    assert result["ssh_key"] == ""
    assert result["auth_mode"] == "password"
    assert cred.last_used_at is not None  # touched for audit/rotation


async def test_credential_group_tier_ssh_key():
    cred = _credential(kind="ssh_key", username="keyuser", secret_plain="PRIVATE_KEY_BLOB")
    node = _node()
    db = _make_db(_Row(cred, "prod"))

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "group:prod"
    assert result["ssh_user"] == "keyuser"
    assert result["ssh_key"] == "PRIVATE_KEY_BLOB"
    assert result["ssh_password"] == ""
    assert result["auth_mode"] == "key"


async def test_credential_group_secret_decrypt_failure_falls_through_to_none():
    """A group Credential whose secret_enc is garbage -> empty secret, no usable
    secret -> falls through to the credential-less 'none' tier. Decryption
    failure is logged, not raised."""
    cred = MagicMock()
    cred.id = uuid.uuid4()
    cred.kind = "username_password"
    cred.username = "cguser"
    cred.secret_enc = "not-valid-fernet-data"
    cred.last_used_at = None
    node = _node()
    db = _make_db(_Row(cred, "prod"), None)  # cred-group tier, then SSH_USERNAME

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "none"
    assert result["ssh_password"] == ""


async def test_no_credential_group_mapping_falls_through_to_none():
    """A node with no credential_groups mapping and no controller key resolves
    to the credential-less 'none' tier."""
    node = _node()
    db = _make_db(None, None)  # cred-group tier (no mapping), SSH_USERNAME

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "none"


# ---------------------------------------------------------------------------
# Controller-key tier
# ---------------------------------------------------------------------------


async def test_controller_key_tier():
    """Bootstrapped node (ssh_host_key set), no group credential -> controller key."""
    node = _node(ssh_host_key="ecdsa-sha2-nistp256 AAAA...")
    db = _make_db(None, None)  # cred-group tier (no mapping), SSH_USERNAME for controller user

    with patch(
        "fleet_platform.services.credential_resolver._read_controller_key",
        return_value="CONTROLLER_KEY",
    ):
        result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "controller"
    assert result["auth_mode"] == "key"
    assert result["ssh_key"] == "CONTROLLER_KEY"


async def test_controller_key_missing_falls_through_to_none():
    """Bootstrapped node but controller key file absent -> credential-less 'none' tier."""
    node = _node(ssh_host_key="ecdsa-sha2-nistp256 AAAA...")
    db = _make_db(None, None)  # cred-group tier (no mapping), SSH_USERNAME

    with patch(
        "fleet_platform.services.credential_resolver._read_controller_key",
        return_value="",
    ):
        result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "none"


async def test_credential_group_wins_over_controller_key():
    """A usable group credential wins over the controller-key tier even when
    ssh_host_key is set."""
    cred = _credential(kind="username_password", username="cguser", secret_plain="cgpw")
    node = _node(ssh_host_key="ecdsa-sha2-nistp256 AAAA...")
    db = _make_db(_Row(cred, "prod"))

    with patch(
        "fleet_platform.services.credential_resolver._read_controller_key",
        return_value="SHOULD_NOT_BE_USED",
    ):
        result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "group:prod"
    assert result["ssh_user"] == "cguser"


# ---------------------------------------------------------------------------
# Credential-less 'none' tier
# ---------------------------------------------------------------------------


async def test_none_tier_no_settings():
    node = _node()
    db = _make_db(None, None)  # cred-group tier (no mapping), SSH_USERNAME

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "none"
    assert result["ssh_user"] == "admin"
    assert result["ssh_password"] == ""
    assert result["ssh_key"] == ""
    assert result["auth_mode"] == "password"


async def test_none_tier_uses_ssh_username_setting_as_login_user():
    """SSH_USERNAME is still read for the login user — never as a password source."""
    node = _node()
    db = _make_db(None, _platform_row("deploy", is_encrypted=False))

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "none"
    assert result["ssh_user"] == "deploy"
    assert result["ssh_password"] == ""


# ---------------------------------------------------------------------------
# node_has_group
# ---------------------------------------------------------------------------


async def test_node_has_group_true():
    member = MagicMock()
    db = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalar_one_or_none.return_value = member
    db.execute.return_value = result

    result_val = await node_has_group(uuid.uuid4(), db)

    assert result_val is True


async def test_node_has_group_false():
    db = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    result_val = await node_has_group(uuid.uuid4(), db)

    assert result_val is False
