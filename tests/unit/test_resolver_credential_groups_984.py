# tests/unit/test_resolver_credential_groups_984.py
"""Unit tests for the ``credential_groups`` resolver tier (#984), now the ONLY
group/node credential source since the #989 Chunk 1 contract (per-node and
legacy ``Group.credential_id`` tiers, plus the global password fallback, were
all removed).

Tier order under test: credential_groups (1) -> controller (2) -> none (3).
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


def _node(ssh_host_key=None):
    node = MagicMock()
    node.id = uuid.uuid4()
    node.minion_id = "node-01"
    node.ssh_host_key = ssh_host_key
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
    """AsyncMock db.execute() side_effect: the first call is consumed via
    ``.all()`` (the credential_groups tier, #1004 C2 — iterates ALL
    credential-bearing groups rather than taking just ``.first()``); remaining
    calls consume from ``scalar_results`` in order (e.g. the SSH_USERNAME
    global setting)."""
    db = AsyncMock(spec=AsyncSession)
    results = []

    r0 = MagicMock()
    r0.all.return_value = [first_results] if first_results is not None else []
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
    r0.all.return_value = [first_results] if first_results is not None else []
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
    """The priority ordering (Group.credential_priority DESC, name ASC) is
    enforced by the ORDER BY in _credential_group_stmt itself — the resolver
    walks the ordered rows via ``.all()`` and returns the first USABLE one
    (#1004 C2). This test confirms the resolver surfaces the winning row when
    it is the only (and therefore first-usable) row returned."""
    winner_cred = _credential(kind="username_password", username="highpriority", secret_plain="hp-pw")
    node = _node()
    # Simulate the DB having already applied ORDER BY credential_priority DESC,
    # name ASC — .all() returns the winning row first.
    db = _make_async_db(_Row(winner_cred, "prod-high"))

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "group:prod-high"
    assert result["ssh_user"] == "highpriority"


async def test_async_no_credential_groups_mapping_falls_through_to_none():
    """Node with NO credential_groups mapping and no controller key resolves
    to the credential-less 'none' tier — there is no legacy group fallback."""
    node = _node()
    db = _make_async_db(None, scalar_results=[None])  # SSH_USERNAME

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "none"
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


def test_sync_no_credential_groups_mapping_falls_through_to_none():
    node = _node()
    db = _make_sync_db(None, scalar_results=[None])  # SSH_USERNAME

    result = resolve_node_credentials_sync(node, db)

    assert result["credential_source"] == "none"
    assert result["ssh_user"] == "admin"
    assert result["ssh_password"] == ""
