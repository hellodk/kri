"""Issue #965 — provision_master must resolve SSH creds like bootstrap, not 'admin'.

provision_master previously used `master.ssh_user or _global_ssh_user or "admin"`,
which ignored the FK-aware credential chain that bootstrap_node uses. A master
promoted from a node (master.node_id set) never inherited that node's working
credentials, so it silently SSHed as 'admin' and failed pre-flight.

_resolve_master_ssh_creds(master, db) must resolve via:
  per-master creds → linked node's resolved credentials (node_id set) → global.
Never silently default the user to 'admin' — an unresolvable user yields ''.

These tests monkeypatch the collaborators (_get_bootstrap_settings,
resolve_node_credentials_sync) so only the priority logic is exercised.
"""

import types

from fleet_platform.workers import ansible_tasks


class _FakeMaster:
    def __init__(self, node_id=None, ssh_user=None, ssh_password_enc=None, ssh_key_enc=None):
        self.node_id = node_id
        self.ssh_user = ssh_user
        self.ssh_password_enc = ssh_password_enc
        self.ssh_key_enc = ssh_key_enc


class _FakeDB:
    """db.execute(...).scalar_one_or_none() returns a sentinel node object."""

    def __init__(self, node=None):
        self._node = node

    def execute(self, *_a, **_k):
        node = self._node
        return types.SimpleNamespace(scalar_one_or_none=lambda: node)


def _patch(monkeypatch, *, global_user="", node_creds=None):
    monkeypatch.setattr(
        ansible_tasks, "_get_bootstrap_settings", lambda _db: (global_user, "globalpw", "pub")
    )
    monkeypatch.setattr(
        ansible_tasks,
        "resolve_node_credentials_sync",
        lambda _node, _db: node_creds or {"ssh_user": "", "ssh_password": "", "ssh_key": ""},
    )


def test_promoted_master_inherits_linked_node_credentials(monkeypatch):
    _patch(monkeypatch, global_user="", node_creds={"ssh_user": "dk", "ssh_password": "nodepw", "ssh_key": ""})
    node = object()
    master = _FakeMaster(node_id="some-uuid", ssh_user=None)
    creds = ansible_tasks._resolve_master_ssh_creds(master, _FakeDB(node))
    assert creds["ssh_user"] == "dk", "must use the linked node's user, not 'admin'"
    assert creds["ssh_password"] == "nodepw"


def test_per_master_ssh_user_takes_priority(monkeypatch):
    _patch(
        monkeypatch,
        global_user="globaluser",
        node_creds={"ssh_user": "dk", "ssh_password": "nodepw", "ssh_key": ""},
    )
    master = _FakeMaster(node_id="some-uuid", ssh_user="operator")
    creds = ansible_tasks._resolve_master_ssh_creds(master, _FakeDB(object()))
    assert creds["ssh_user"] == "operator"


def test_no_admin_fallback_when_nothing_resolves(monkeypatch):
    _patch(monkeypatch, global_user="", node_creds=None)
    master = _FakeMaster(node_id=None, ssh_user=None)
    creds = ansible_tasks._resolve_master_ssh_creds(master, _FakeDB(None))
    assert creds["ssh_user"] == "", "must NOT silently default to 'admin'"
