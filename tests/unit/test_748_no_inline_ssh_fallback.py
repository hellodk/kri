"""#748 (ARC-4) + #989 (Chunk 1): no inline SSH fallback, no node/legacy-group tier.

Before #748, ``credential_resolver`` and ``ssh_credential_link`` read the
deprecated inline ``ssh_*`` columns on nodes/groups as a fallback when no
credential was linked — a second secret-resolution path. #989 Chunk 1 went
further and contracted the model to GROUP-ONLY: the per-node
``Node.credential_id`` FK, the legacy ``Group.credential_id`` FK, and the
global-password fallback were all dropped along with their columns. These
tests pin the current contract:

* resolution flows ONLY through ``credential_groups`` (+ the controller-key
  tier), never inline columns, never a per-node/legacy-group FK, never a
  global password;
* a node with only inline-style poison data and no credential_groups mapping
  resolves to no usable secret and :func:`require_usable_node_credentials`
  raises;
* the inline helper functions and the legacy tier helpers are gone, so none of
  these dual paths can silently come back.
"""

from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.services import credential_resolver
from fleet_platform.services.credential_resolver import (
    NoUsableCredentialError,
    require_usable_node_credentials,
    require_usable_node_credentials_sync,
    resolve_node_credentials,
    resolve_node_credentials_sync,
)
from fleet_platform.services.platform_settings_svc import encrypt_secret

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(cg_result, *scalar_returns):
    """AsyncMock db: first execute() is consumed via ``.first()`` (credential_groups
    tier); remaining calls via ``.scalar_one_or_none()`` (e.g. SSH_USERNAME)."""
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


def _sync_db(cg_result, *scalar_returns):
    db = MagicMock()
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


def _node_with_inline(ssh_host_key=None):
    """A node carrying *only* legacy inline-style poison attributes.

    Uses a plain MagicMock so the inline attributes exist as object attributes —
    if the resolver still read them, these poison values would leak into the
    result. They must not. There is no ``credential_id`` attribute at all
    (#989 — the column is gone from the real model).
    """
    node = MagicMock(spec=["id", "minion_id", "ssh_host_key"])
    node.id = "legacy-node-id"
    node.minion_id = "legacy-node-01"
    node.ssh_host_key = ssh_host_key
    return node


def _credential(kind="username_password", username="cuser", secret_plain="cpw"):
    cred = MagicMock()
    cred.id = "cred-id"
    cred.kind = kind
    cred.username = username
    cred.secret_enc = encrypt_secret(secret_plain) if secret_plain is not None else ""
    cred.last_used_at = None
    return cred


class _Row:
    """Mimics a SQLAlchemy (Credential, group_name) Row consumed via ``.first()``."""

    def __init__(self, cred, name):
        self._t = (cred, name)

    def __iter__(self):
        return iter(self._t)


# ---------------------------------------------------------------------------
# Credential-store resolution still works (happy path preserved)
# ---------------------------------------------------------------------------


async def test_resolve_via_credential_groups_works():
    cred = _credential(username="cuser", secret_plain="cpw")
    node = _node_with_inline()
    db = _make_db(_Row(cred, "prod"))

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "group:prod"
    assert result["ssh_user"] == "cuser"
    assert result["ssh_password"] == "cpw"


def test_resolve_sync_via_credential_groups_works():
    cred = _credential(kind="ssh_key", username="keyuser", secret_plain="KEYBLOB")
    node = _node_with_inline()
    db = _sync_db(_Row(cred, "prod"))

    result = resolve_node_credentials_sync(node, db)

    assert result["credential_source"] == "group:prod"
    assert result["ssh_key"] == "KEYBLOB"
    assert result["auth_mode"] == "key"


# ---------------------------------------------------------------------------
# Inline columns / node-level / legacy-group tiers are never read
# ---------------------------------------------------------------------------


async def test_node_inline_data_ignored_no_credential_groups_mapping():
    """A node with inline-style poison attrs but no credential_groups mapping
    must NOT resolve to any inline value — it falls through to the credential-
    less 'none' tier (there is no global password fallback, #989)."""
    node = _node_with_inline()
    # credential_groups tier -> None, SSH_USERNAME -> None
    db = _make_db(None, None)

    result = await resolve_node_credentials(node, db)

    assert result["credential_source"] == "none"
    assert result["ssh_user"] == "admin"  # default, not any poisoned value
    assert result["ssh_password"] == ""
    assert result["ssh_key"] == ""


def test_sync_node_inline_data_ignored_no_credential_groups_mapping():
    node = _node_with_inline()
    db = _sync_db(None, None)

    result = resolve_node_credentials_sync(node, db)

    assert result["credential_source"] == "none"
    assert result["ssh_user"] == "admin"
    assert result["ssh_password"] == ""


def test_no_node_level_or_legacy_group_tier_helpers_exist():
    """The per-node and legacy-Group.credential_id tiers were removed for good
    in #989 Chunk 1 — their helper must not exist. The read-only audit helper
    (now credential_groups-only) is untouched and must still exist."""
    assert not hasattr(credential_resolver, "_primary_group_stmt")
    assert hasattr(credential_resolver, "nodes_using_credential")


# ---------------------------------------------------------------------------
# Loud failure: missing credential raises instead of degrading silently
# ---------------------------------------------------------------------------


async def test_require_raises_for_inline_only_node():
    """A node with only inline poison data and no credential_groups mapping has
    no usable secret — require_usable_node_credentials must raise."""
    node = _node_with_inline()
    db = _make_db(None, None)

    try:
        await require_usable_node_credentials(node, db)
        raise AssertionError("expected NoUsableCredentialError")
    except NoUsableCredentialError as exc:
        assert "legacy-node-01" in str(exc)


def test_require_sync_raises_for_inline_only_node():
    node = _node_with_inline()
    db = _sync_db(None, None)

    try:
        require_usable_node_credentials_sync(node, db)
        raise AssertionError("expected NoUsableCredentialError")
    except NoUsableCredentialError as exc:
        assert "group" in str(exc)


async def test_require_returns_creds_when_credential_present():
    cred = _credential(username="cuser", secret_plain="cpw")
    node = _node_with_inline()
    db = _make_db(_Row(cred, "prod"))

    result = await require_usable_node_credentials(node, db)

    assert result["ssh_password"] == "cpw"


# ---------------------------------------------------------------------------
# Structural guards: the dual path cannot silently return
# ---------------------------------------------------------------------------


def test_inline_helpers_removed():
    assert not hasattr(credential_resolver, "_inline_node_creds")
    assert not hasattr(credential_resolver, "_inline_group_creds")


async def test_owner_secret_flags_has_no_inline_params():
    """owner_secret_flags resolves solely through the Credential store. The
    deprecated ``inline_password_enc`` / ``inline_key_enc`` parameters were
    dropped with the inline columns (#913), so the dual secret path cannot
    silently come back, and an owner with no credential_id reports no secret."""
    import inspect

    from fleet_platform.services.ssh_credential_link import owner_secret_flags

    # Structural guard: the inline read-path parameters must not reappear.
    params = set(inspect.signature(owner_secret_flags).parameters)
    assert "inline_password_enc" not in params
    assert "inline_key_enc" not in params

    db = AsyncMock(spec=AsyncSession)
    has_password, has_key = await owner_secret_flags(db, credential_id=None)

    assert has_password is False
    assert has_key is False
    db.get.assert_not_called()


async def test_owner_secret_flags_reads_credential_store():
    from fleet_platform.services.ssh_credential_link import owner_secret_flags

    cred = _credential(kind="username_password", secret_plain="cpw")
    db = AsyncMock(spec=AsyncSession)
    db.get.return_value = cred

    has_password, has_key = await owner_secret_flags(db, credential_id=cred.id)

    assert has_password is True
    assert has_key is False
