# tests/unit/test_resolver_credential_groups_984.py
"""Unit tests for the #984 credential_groups resolver tier (Phase 2a).

Migration 065 (Phase 1) added the ``credential_groups`` association table
(``credential_id``, ``group_id UNIQUE``). This phase makes both the async and
sync resolvers PREFER that association over the legacy ``Group.credential_id``
column, while keeping the legacy tier as an expand-contract fallback.

Tier order under test: node FK (1) -> credential_groups (1b, NEW) -> legacy
group FK (2) -> controller (3) -> global (4).
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.services.credential_resolver import (
    resolve_node_credentials,
    resolve_node_credentials_sync,
)
from fleet_platform.services.platform_settings_svc import encrypt_secret

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node(ssh_host_key=None, credential_id=None):
    node = MagicMock()
    node.id = uuid.uuid4()
    node.minion_id = "node-01"
    node.ssh_host_key = ssh_host_key
    node.credential_id = credential_id
    return node


def _credential(kind="username_password", username="cuser", secret_plain="cpw"):
    cred = MagicMock()
    cred.id = uuid.uuid4()
    cred.kind = kind
    cred.username = username
    cred.secret_enc = encrypt_secret(secret_plain) if secret_plain is not None else ""
    cred.last_used_at = None
    return cred


class _Row:
    """A (Credential, group_name) row returned by the credential_groups tier's
    ``.first()`` — supports tuple-unpacking like a real SQLAlchemy Row."""

    def __init__(self, cred, name):
        self._t = (cred, name)

    def __iter__(self):
        return iter(self._t)


def _make_async_db(first_results, scalar_results=None):
    """AsyncMock db.execute() side_effect: each item is either consumed via
    ``.first()`` (credential_groups tier) or ``.scalar_one_or_none()`` (legacy
    group / global tiers), in call order. ``first_results`` supplies the very
    first db.execute() call (the credential_groups tier); remaining calls
    consume from ``scalar_results`` in order."""
    db = AsyncMock(spec=AsyncSession)
    results = []

    r0 = MagicMock()
    r0.first.return_value = first_results
    results.append(r0)

    for val in scalar_results or []:
        r = MagicMock()
        r.scalar_one_or_none.return_value = val
        results.append(r)

    db.execute.side_effect = results
    return db


def _make_sync_db(first_results, scalar_results=None):
    db = MagicMock()
    results = []

    r0 = MagicMock()
    r0.first.return_value = first_results
    results.append(r0)

    for val in scalar_results or []:
        r = MagicMock()
        r.scalar_one_or_none.return_value = val
        results.append(r)

    db.execute.side_effect = results
    return db


# ---------------------------------------------------------------------------
# Async resolver
# ---------------------------------------------------------------------------


async def test_async_credential_groups_tier_resolves():
    """Node in a group mapped via credential_groups -> resolves that credential,
    source 'group:<name>'."""
    cred = _credential(kind="username_password", username="cguser", secret_plain="cgpw")
    node = _node()
    db = _make_async_db(_Row(cred, "prod"))

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "group:prod"
    assert result["ssh_user"] == "cguser"
    assert result["ssh_password"] == "cgpw"
    assert result["auth_mode"] == "password"


async def test_async_credential_groups_tier_ssh_key():
    cred = _credential(kind="ssh_key", username="cgkeyuser", secret_plain="CG_KEY_BLOB")
    node = _node()
    db = _make_async_db(_Row(cred, "prod"))

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "group:prod"
    assert result["ssh_key"] == "CG_KEY_BLOB"
    assert result["auth_mode"] == "key"


async def test_async_credential_groups_priority_ordering_handled_by_query():
    """The priority tiebreak (Group.credential_priority DESC, name ASC) is
    enforced by the ORDER BY + LIMIT 1 in _credential_group_stmt itself — the
    resolver just takes whatever .first() returns. This test confirms the
    resolver surfaces exactly that single winning row rather than re-deriving
    priority itself."""
    winner_cred = _credential(kind="username_password", username="highpriority", secret_plain="hp-pw")
    node = _node()
    # Simulate the DB having already applied ORDER BY credential_priority DESC,
    # name ASC, LIMIT 1 — .first() returns only the winning row.
    db = _make_async_db(_Row(winner_cred, "prod-high"))

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "group:prod-high"
    assert result["ssh_user"] == "highpriority"


async def test_async_no_credential_groups_mapping_falls_through_to_legacy_group():
    """Node with NO credential_groups mapping falls through to the legacy group
    tier exactly as before (#699 behaviour preserved)."""
    from unittest.mock import MagicMock as _MM

    legacy_cred = _credential(kind="username_password", username="legacyuser", secret_plain="legacypw")
    legacy_group = _MM()
    legacy_group.name = "legacy-prod"
    legacy_group.credential_id = legacy_cred.id
    legacy_group.credential_priority = 0

    node = _node()
    db = _make_async_db(None, scalar_results=[legacy_group])
    db.get = AsyncMock(return_value=legacy_cred)

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "group:legacy-prod"
    assert result["ssh_user"] == "legacyuser"
    assert result["ssh_password"] == "legacypw"


async def test_async_no_credential_groups_no_legacy_group_falls_through_to_global():
    """Node with no credential_groups mapping and no legacy group falls all the
    way through to controller/global exactly as before."""
    node = _node()
    db = _make_async_db(None, scalar_results=[None, None, None])  # legacy group, SSH_USERNAME, SSH_PASSWORD

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "global"
    assert result["ssh_user"] == "admin"
    assert result["ssh_password"] == ""


# ---------------------------------------------------------------------------
# Sync resolver
# ---------------------------------------------------------------------------


def test_sync_credential_groups_tier_resolves():
    cred = _credential(kind="username_password", username="cguser", secret_plain="cgpw")
    node = _node()
    db = _make_sync_db(_Row(cred, "prod"))

    result = resolve_node_credentials_sync(node, db)

    assert result["credential_source"] == "group:prod"
    assert result["ssh_user"] == "cguser"
    assert result["ssh_password"] == "cgpw"


def test_sync_credential_groups_tier_ssh_key():
    cred = _credential(kind="ssh_key", username="cgkeyuser", secret_plain="CG_KEY_BLOB")
    node = _node()
    db = _make_sync_db(_Row(cred, "prod"))

    result = resolve_node_credentials_sync(node, db)

    assert result["credential_source"] == "group:prod"
    assert result["ssh_key"] == "CG_KEY_BLOB"
    assert result["auth_mode"] == "key"


def test_sync_no_credential_groups_mapping_falls_through_to_legacy_group():
    legacy_cred = _credential(kind="username_password", username="legacyuser", secret_plain="legacypw")
    legacy_group = MagicMock()
    legacy_group.name = "legacy-prod"
    legacy_group.credential_id = legacy_cred.id
    legacy_group.credential_priority = 0

    node = _node()
    db = _make_sync_db(None, scalar_results=[legacy_group])
    db.get.return_value = legacy_cred

    result = resolve_node_credentials_sync(node, db)

    assert result["credential_source"] == "group:legacy-prod"
    assert result["ssh_user"] == "legacyuser"
    assert result["ssh_password"] == "legacypw"


def test_sync_no_credential_groups_no_legacy_group_falls_through_to_global():
    node = _node()
    db = _make_sync_db(None, scalar_results=[None, None, None])  # legacy group, SSH_USERNAME, SSH_PASSWORD

    result = resolve_node_credentials_sync(node, db)

    assert result["credential_source"] == "global"
    assert result["ssh_user"] == "admin"
    assert result["ssh_password"] == ""


def test_sync_node_credential_still_wins_over_credential_groups_tier():
    """Node-level FK (tier 1) still wins over the new credential_groups tier
    (tier 1b) — priority chain preserved."""
    node_cred = _credential(kind="username_password", username="nodeuser", secret_plain="nodepw")
    node = _node(credential_id=node_cred.id)
    db = MagicMock()
    db.get.return_value = node_cred

    result = resolve_node_credentials_sync(node, db)

    assert result["credential_source"] == "node"
    assert result["ssh_user"] == "nodeuser"
    db.execute.assert_not_called()  # tier 1 short-circuits before credential_groups tier runs
