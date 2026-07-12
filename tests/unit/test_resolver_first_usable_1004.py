# tests/unit/test_resolver_first_usable_1004.py
"""Unit tests for #1004 C2 — the resolver must use the first USABLE
credential-bearing group, not just the top-priority one.

If a node belongs to 2+ credential-bearing groups, ``_credential_group_stmt``
orders them by ``credential_priority`` DESC, then name ASC. Before this fix,
the resolvers took ``.first()`` — if the top-priority group's credential could
not be decrypted (or was empty), resolution gave up entirely instead of
trying the next credential-bearing group. These tests confirm the resolvers
(and ``nodes_using_credential``) now walk ALL ordered rows and use the first
one whose secret is actually usable.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.services.credential_resolver import (
    _credential_group_stmt,
    nodes_using_credential,
    resolve_node_credentials,
    resolve_node_credentials_sync,
)
from fleet_platform.services.platform_settings_svc import encrypt_secret

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Row:
    """Mimics a SQLAlchemy (Credential, group_name) Row consumed via ``.all()``."""

    def __init__(self, cred, name):
        self._t = (cred, name)

    def __iter__(self):
        return iter(self._t)


def _node(ssh_host_key=None):
    node = MagicMock()
    node.id = uuid.uuid4()
    node.minion_id = "node-01"
    node.ssh_host_key = ssh_host_key
    return node


def _credential(username="u", secret_plain="pw"):
    cred = MagicMock()
    cred.id = uuid.uuid4()
    cred.kind = "username_password"
    cred.username = username
    cred.secret_enc = encrypt_secret(secret_plain)
    cred.last_used_at = None
    return cred


def _unusable_credential(username="topuser"):
    """A credential whose ``secret_enc`` is garbage -> decrypts to '' -> unusable."""
    cred = MagicMock()
    cred.id = uuid.uuid4()
    cred.kind = "username_password"
    cred.username = username
    cred.secret_enc = "not-valid-fernet-data"
    cred.last_used_at = None
    return cred


# ---------------------------------------------------------------------------
# _credential_group_stmt no longer limits to 1 row
# ---------------------------------------------------------------------------


def test_credential_group_stmt_has_no_limit():
    """#1004 C2: the statement must return ALL ordered rows, not just the
    top-priority one — no ``.limit(1)``."""
    stmt = _credential_group_stmt(uuid.uuid4())
    assert stmt._limit_clause is None
    assert "LIMIT" not in str(stmt)


# ---------------------------------------------------------------------------
# Async resolver — falls through to the next usable group
# ---------------------------------------------------------------------------


async def test_async_resolver_falls_through_to_second_usable_group():
    """Top-priority group's credential is undecryptable; the resolver must use
    the second (lower-priority) group's usable credential instead of giving
    up and returning the credential-less 'none' tier."""
    top_cred = _unusable_credential(username="topuser")
    second_cred = _credential(username="seconduser", secret_plain="secondpw")
    node = _node()

    db = AsyncMock(spec=AsyncSession)
    group_result = MagicMock()
    group_result.all.return_value = [_Row(top_cred, "high-prio"), _Row(second_cred, "low-prio")]
    db.execute.side_effect = [group_result]

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "group:low-prio"
    assert result["ssh_user"] == "seconduser"
    assert result["ssh_password"] == "secondpw"


async def test_async_resolver_all_unusable_falls_through_to_controller():
    """All credential-bearing groups are unusable AND the node is bootstrapped
    -> falls all the way through to the controller-key tier."""
    top_cred = _unusable_credential(username="topuser")
    second_cred = _unusable_credential(username="seconduser")
    node = _node(ssh_host_key="ecdsa-sha2-nistp256 AAAA...")

    db = AsyncMock(spec=AsyncSession)
    group_result = MagicMock()
    group_result.all.return_value = [_Row(top_cred, "high-prio"), _Row(second_cred, "low-prio")]
    settings_result = MagicMock()
    settings_result.scalar_one_or_none.return_value = None
    db.execute.side_effect = [group_result, settings_result]

    with patch(
        "fleet_platform.services.credential_resolver._read_controller_key",
        return_value="CONTROLLER_KEY",
    ):
        result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "controller"
    assert result["ssh_key"] == "CONTROLLER_KEY"


# ---------------------------------------------------------------------------
# Sync resolver — mirrors the async behavior
# ---------------------------------------------------------------------------


def test_sync_resolver_falls_through_to_second_usable_group():
    top_cred = _unusable_credential(username="topuser")
    second_cred = _credential(username="seconduser", secret_plain="secondpw")
    node = _node()

    db = MagicMock()
    group_result = MagicMock()
    group_result.all.return_value = [_Row(top_cred, "high-prio"), _Row(second_cred, "low-prio")]
    db.execute.side_effect = [group_result]

    result = resolve_node_credentials_sync(node, db)

    assert result["credential_source"] == "group:low-prio"
    assert result["ssh_user"] == "seconduser"
    assert result["ssh_password"] == "secondpw"


def test_sync_resolver_three_groups_uses_third_when_first_two_unusable():
    top_cred = _unusable_credential(username="topuser")
    mid_cred = _unusable_credential(username="miduser")
    winning_cred = _credential(username="winninguser", secret_plain="winpw")
    node = _node()

    db = MagicMock()
    group_result = MagicMock()
    group_result.all.return_value = [
        _Row(top_cred, "prio-3"),
        _Row(mid_cred, "prio-2"),
        _Row(winning_cred, "prio-1"),
    ]
    db.execute.side_effect = [group_result]

    result = resolve_node_credentials_sync(node, db)

    assert result["credential_source"] == "group:prio-1"
    assert result["ssh_user"] == "winninguser"


# ---------------------------------------------------------------------------
# nodes_using_credential — audit view mirrors first-usable-wins resolution
# ---------------------------------------------------------------------------


async def test_nodes_using_credential_counts_first_usable_only():
    """A node whose top-priority group credential is unusable, but whose
    second group resolves to ``credential_id``, must be counted under the
    SECOND group's source."""
    top_cred = _unusable_credential(username="topuser")
    winning_cred = _credential(username="seconduser", secret_plain="secondpw")
    node = _node()

    db = AsyncMock(spec=AsyncSession)
    candidates_result = MagicMock()
    candidates_scalars = MagicMock()
    candidates_scalars.all.return_value = [node]
    candidates_result.scalars.return_value = candidates_scalars

    group_result = MagicMock()
    group_result.all.return_value = [_Row(top_cred, "high-prio"), _Row(winning_cred, "low-prio")]

    db.execute.side_effect = [candidates_result, group_result]

    results = await nodes_using_credential(winning_cred.id, db)

    assert results == [(node, "group:low-prio")]


async def test_nodes_using_credential_excludes_unusable_top_priority_credential():
    """Querying by the UNUSABLE top-priority credential's id must return no
    results — that credential never wins resolution for this node, so it must
    not be reported as "in use" by it."""
    top_cred = _unusable_credential(username="topuser")
    winning_cred = _credential(username="seconduser", secret_plain="secondpw")
    node = _node()

    db = AsyncMock(spec=AsyncSession)
    candidates_result = MagicMock()
    candidates_scalars = MagicMock()
    candidates_scalars.all.return_value = [node]
    candidates_result.scalars.return_value = candidates_scalars

    group_result = MagicMock()
    group_result.all.return_value = [_Row(top_cred, "high-prio"), _Row(winning_cred, "low-prio")]

    db.execute.side_effect = [candidates_result, group_result]

    results = await nodes_using_credential(top_cred.id, db)

    assert results == []
