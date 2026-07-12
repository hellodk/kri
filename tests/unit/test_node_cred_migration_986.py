"""Issue #986 Phase 2c — migrate import/bootstrap/node callers off per-node
credentials (``Node.credential_id``).

Credentials now reach a node via its group's ``credential_groups`` association
(#983/#984). This phase stops WRITING ``Node.credential_id`` from the three
callers that used to create per-node ``Credential`` rows: the bulk-import
commit path (``fleet.py``), the shared bootstrap-queuing service
(``bootstrap_svc.py``), and the node PATCH endpoint (``nodes.py``). The column
itself is NOT dropped — legacy rows and the resolver's tier-1 read are
untouched; only new per-node writes are removed.

Source-contract tests read the actual route/service source (via
``Path(__file__)`` relative paths, never absolute) and assert the offending
write patterns are gone. A behavioral test exercises
``resolve_node_credentials`` (mocked DB, following the pattern in
``test_resolver_credential_groups_984.py``) to confirm a node's *resolved*
credential comes from its group, not a per-node FK.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.services.credential_resolver import resolve_node_credentials
from fleet_platform.services.platform_settings_svc import encrypt_secret

_ROOT = Path(__file__).resolve().parents[2]
_FLEET_PY = _ROOT / "fleet_platform" / "api" / "routes" / "fleet.py"
_BOOTSTRAP_SVC_PY = _ROOT / "fleet_platform" / "services" / "bootstrap_svc.py"
_NODES_PY = _ROOT / "fleet_platform" / "api" / "routes" / "nodes.py"


# ─── source-contract: fleet.py import_commit no longer writes node.credential_id ──


def test_fleet_import_commit_does_not_write_node_credential_id():
    src = _FLEET_PY.read_text()
    assert "node.credential_id = " not in src, (
        "fleet.py import_commit must not create a per-node Credential and write "
        "node.credential_id — nodes get credentials via their group (#986)."
    )


def test_fleet_import_commit_does_not_upsert_owner_ssh_credential():
    src = _FLEET_PY.read_text()
    assert "upsert_owner_ssh_credential" not in src, (
        "fleet.py must no longer call upsert_owner_ssh_credential to create a "
        "per-node Credential during import (#986)."
    )


def test_fleet_import_commit_falls_back_to_default_group():
    src = _FLEET_PY.read_text()
    assert 'Group.name == "default"' in src, (
        "import_commit should add a node with no explicit group_id to the "
        "seeded 'default' group (migration 065) so it still resolves a "
        "credential via credential_groups."
    )


# ─── source-contract: bootstrap_svc.py no longer writes node.credential_id ────────


def test_bootstrap_svc_does_not_write_node_credential_id():
    src = _BOOTSTRAP_SVC_PY.read_text()
    assert "node.credential_id = " not in src, (
        "bootstrap_svc.queue_node_bootstrap must not persist bootstrap-time SSH "
        "creds as a per-node Credential — the resolver reads from the node's "
        "group (#986)."
    )


def test_bootstrap_svc_does_not_upsert_owner_ssh_credential():
    src = _BOOTSTRAP_SVC_PY.read_text()
    assert "upsert_owner_ssh_credential" not in src


# ─── source-contract: nodes.py PATCH no longer writes node.credential_id ──────────


def test_nodes_patch_does_not_write_node_credential_id():
    src = _NODES_PY.read_text()
    assert "node.credential_id = " not in src, (
        "nodes.py update_node (PATCH /{node_id}) must not set node.credential_id "
        "from payload.credential_id or an inline ssh_* upsert — credentials are "
        "group-scoped (#986)."
    )


def test_nodes_does_not_upsert_owner_ssh_credential():
    src = _NODES_PY.read_text()
    assert "upsert_owner_ssh_credential" not in src


def test_nodes_credential_bearing_groups_query_uses_credential_groups():
    """The /{node_id}/credential conflict-groups query must join credential_groups
    (CredentialGroup), not filter on the legacy Group.credential_id column."""
    src = _NODES_PY.read_text()
    assert "CredentialGroup" in src
    assert "Group.credential_id.isnot(None)" not in src, (
        "the credential-bearing-groups query in get_node_resolved_credential must "
        "use the normalized credential_groups association, not the legacy "
        "Group.credential_id column (#986, continuing #984's resolver cutover)."
    )


def test_nodes_uses_resolver_for_displayed_credential():
    """get_node / update_node must surface the resolver's output, not a raw
    db.get(Credential, node.credential_id) lookup."""
    src = _NODES_PY.read_text()
    assert "resolve_node_credentials(node, db)" in src
    assert "db.get(Credential, node.credential_id)" not in src


# ─── behavioral: a node's displayed credential reflects its group's, not a per-node one ──


def _node(credential_id=None, ssh_host_key=None):
    node = MagicMock()
    node.id = "node-uuid"
    node.minion_id = "node-01"
    node.credential_id = credential_id
    node.ssh_host_key = ssh_host_key
    return node


def _credential(username="groupuser", secret_plain="grouppw"):
    cred = MagicMock()
    cred.id = "cred-uuid"
    cred.kind = "username_password"
    cred.username = username
    cred.secret_enc = encrypt_secret(secret_plain)
    cred.last_used_at = None
    return cred


class _Row:
    """Mimics a SQLAlchemy (Credential, group_name) Row for .first()."""

    def __init__(self, cred, name):
        self._t = (cred, name)

    def __iter__(self):
        return iter(self._t)


async def test_resolved_credential_comes_from_group_not_node():
    """A node with no per-node credential_id, but whose group carries one via
    credential_groups, resolves to the GROUP credential (#986) — this is what
    nodes.py now surfaces instead of a per-node Credential lookup."""
    node = _node(credential_id=None)
    group_cred = _credential(username="groupuser", secret_plain="grouppw")

    db = AsyncMock(spec=AsyncSession)
    cg_result = MagicMock()
    cg_result.first.return_value = _Row(group_cred, "default")
    db.execute.side_effect = [cg_result]

    creds = await resolve_node_credentials(node, db)

    assert creds["credential_source"] == "group:default"
    assert creds["ssh_user"] == "groupuser"
    assert creds["ssh_password"] == "grouppw"


async def test_node_level_credential_id_no_longer_populated_by_new_writers():
    """A freshly-imported/bootstrapped node has credential_id=None (nothing
    writes it anymore); resolution still succeeds via the group tier."""
    node = _node(credential_id=None)  # simulates a node created post-#986
    group_cred = _credential(username="groupuser", secret_plain="grouppw")

    db = AsyncMock(spec=AsyncSession)
    cg_result = MagicMock()
    cg_result.first.return_value = _Row(group_cred, "default")
    db.execute.side_effect = [cg_result]

    creds = await resolve_node_credentials(node, db)

    # Node-level tier (1) was never reached because node.credential_id is None —
    # confirmed indirectly: db.get was never called for a node-level Credential.
    db.get.assert_not_called()
    assert creds["credential_source"] == "group:default"
