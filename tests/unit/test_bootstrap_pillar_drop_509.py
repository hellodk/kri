"""Tests for #509 — drop vestigial local pillar write from bootstrap_node.

Two concerns:
a. bootstrap_node must NOT write/create the local pillar dir; it must not fail
   when /srv/salt/pillar is missing/unwritable.
b. Any failure inside bootstrap_node must leave bootstrap_status as a terminal
   value ('failed'), never leave it stuck at 'bootstrapping'.

Updated in #520: ansible_runner.run → run_async; SaltMaster gate mocked.
"""

import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers — source-level assertions (fast, no imports of heavy deps)
# ---------------------------------------------------------------------------

SRC = Path("fleet_platform/workers/ansible_tasks.py").read_text()

BOOTSTRAP_FN_START = SRC.find("def bootstrap_node")
_NEXT_FN = SRC.find("\ndef ", BOOTSTRAP_FN_START + 20)
BOOTSTRAP_BODY = SRC[BOOTSTRAP_FN_START : _NEXT_FN if _NEXT_FN > 0 else BOOTSTRAP_FN_START + 12000]


# ---------------------------------------------------------------------------
# (a) Pillar write must be gone from bootstrap_node
# ---------------------------------------------------------------------------


def test_write_pillar_file_not_called_in_bootstrap():
    """_write_pillar_file must not appear anywhere in the bootstrap_node body."""
    assert "_write_pillar_file" not in BOOTSTRAP_BODY, (
        "_write_pillar_file is still called inside bootstrap_node — must be removed (#509)"
    )


def test_get_pillar_dir_not_called_in_bootstrap():
    """_get_pillar_dir must not be called inside bootstrap_node (pillar lookup is vestigial)."""
    assert "_get_pillar_dir" not in BOOTSTRAP_BODY, (
        "_get_pillar_dir is still called inside bootstrap_node — must be removed (#509)"
    )


def test_pillar_dir_writable_not_called_in_bootstrap():
    """_pillar_dir_writable must not be called inside bootstrap_node."""
    assert "_pillar_dir_writable" not in BOOTSTRAP_BODY, (
        "_pillar_dir_writable is still called inside bootstrap_node — must be removed (#509)"
    )


def test_node_token_delivered_via_extravars():
    """node_token must still be passed via extravars to ansible-runner (the correct delivery path)."""
    assert '"node_token"' in BOOTSTRAP_BODY or "'node_token'" in BOOTSTRAP_BODY, (
        "node_token must still appear in ansible-runner extravars — token delivery must not be broken"
    )
    assert '"ingest_url"' in BOOTSTRAP_BODY or "'ingest_url'" in BOOTSTRAP_BODY, (
        "ingest_url must still appear in ansible-runner extravars"
    )


# ---------------------------------------------------------------------------
# (b) Any exception must leave bootstrap_status as a terminal state
# ---------------------------------------------------------------------------


def _make_node(node_id: uuid.UUID, minion_id: str = "mm1.local") -> MagicMock:
    node = MagicMock()
    node.id = node_id
    node.minion_id = minion_id
    node.bootstrap_status = "pending"
    node.bootstrap_ip = None
    node.bootstrap_logs = ""
    node.bootstrap_error = None
    node.ssh_key_enc = None
    node.ssh_host_key = None
    node.node_token_hash = None
    node.salt_master_id = None  # no master FK → fallback path (#520)
    return node


def _make_run_async(status: str = "successful", rc: int = 0):
    """Return a fake (thread, runner) pair for ansible_runner.run_async."""
    fake_runner = MagicMock()
    fake_runner.status = status
    fake_runner.rc = rc

    fake_thread = MagicMock()
    fake_thread.is_alive.return_value = False  # loop exits immediately

    return (fake_thread, fake_runner)


def _make_db_ctx(node: MagicMock) -> MagicMock:
    """Return a mock context manager that yields a DB session holding ``node``."""
    run_row = MagicMock()
    run_row.id = uuid.uuid4()
    run_row.status = "running"

    session = MagicMock()
    # scalar_one_or_none returns the node for Node queries, run_row for BootstrapRun
    session.execute.return_value.scalar_one_or_none.return_value = node
    session.execute.return_value.scalar_one.return_value = node

    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=session)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx, session, run_row


def test_bootstrap_status_is_terminal_when_ansible_raises(tmp_path):
    """If ansible_runner.run_async raises unexpectedly, bootstrap_status must be 'failed', not 'bootstrapping'."""
    from fleet_platform.workers.ansible_tasks import bootstrap_node

    node_id = uuid.uuid4()
    node = _make_node(node_id)

    final_statuses: list[str] = []

    def fake_get_sync_db():
        run_row = MagicMock()
        run_row.id = uuid.uuid4()
        run_row.status = "running"
        run_row.finished_at = None

        session = MagicMock()

        def execute_side_effect(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = node
            result.scalar_one.return_value = node
            result.scalars.return_value.first.return_value = None  # no SaltMaster row
            return result

        session.execute.side_effect = execute_side_effect

        def commit_side_effect():
            final_statuses.append(node.bootstrap_status)

        session.commit.side_effect = commit_side_effect
        session.add = MagicMock()

        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=session)
        ctx.__exit__ = MagicMock(return_value=False)
        return ctx

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", side_effect=fake_get_sync_db),
        patch(
            "fleet_platform.workers.ansible_tasks._get_bootstrap_settings",
            return_value=("admin", "pw", "pubkey"),
        ),
        patch(
            "fleet_platform.workers.ansible_tasks.resolve_node_credentials_sync",
            return_value={
                "ssh_user": "admin",
                "ssh_password": "pw",
                "ssh_key": "",
                "auth_mode": "password",
                "credential_source": "node",
            },
        ),
        patch(
            "fleet_platform.workers.ansible_tasks.ansible_runner.run_async",
            side_effect=RuntimeError("simulated crash"),
        ),
        patch("fleet_platform.workers.ansible_tasks.secrets.token_urlsafe", return_value="FAKE_TOKEN"),
        patch("fleet_platform.workers.ansible_tasks.hash_password", return_value="hashed"),
    ):
        # Task must not propagate the exception unhandled to the caller
        # (either swallows it and returns error dict, or re-raises after setting terminal status).
        # We accept either behaviour as long as the node is never left at 'bootstrapping'.
        try:
            bootstrap_node(node_id=str(node_id), target_ip="10.0.0.1")
        except Exception:
            pass  # re-raising after recording terminal status is also acceptable

    # The node must NOT be stuck at 'bootstrapping'
    assert node.bootstrap_status != "bootstrapping", (
        f"bootstrap_status is still 'bootstrapping' after ansible raised — got {node.bootstrap_status!r}"
    )
    # It must have been set to 'failed'
    assert node.bootstrap_status == "failed", (
        f"Expected bootstrap_status='failed' after crash, got {node.bootstrap_status!r}"
    )


def test_bootstrap_error_is_set_when_ansible_raises(tmp_path):
    """If ansible_runner.run_async raises, bootstrap_error must be a non-empty string."""
    from fleet_platform.workers.ansible_tasks import bootstrap_node

    node_id = uuid.uuid4()
    node = _make_node(node_id)

    def fake_get_sync_db():
        run_row = MagicMock()
        run_row.id = uuid.uuid4()
        run_row.status = "running"
        run_row.finished_at = None

        session = MagicMock()

        def execute_side_effect(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = node
            result.scalar_one.return_value = node
            result.scalars.return_value.first.return_value = None  # no SaltMaster row
            return result

        session.execute.side_effect = execute_side_effect
        session.add = MagicMock()
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=session)
        ctx.__exit__ = MagicMock(return_value=False)
        return ctx

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", side_effect=fake_get_sync_db),
        patch(
            "fleet_platform.workers.ansible_tasks._get_bootstrap_settings",
            return_value=("admin", "pw", "pubkey"),
        ),
        patch(
            "fleet_platform.workers.ansible_tasks.resolve_node_credentials_sync",
            return_value={
                "ssh_user": "admin",
                "ssh_password": "pw",
                "ssh_key": "",
                "auth_mode": "password",
                "credential_source": "node",
            },
        ),
        patch(
            "fleet_platform.workers.ansible_tasks.ansible_runner.run_async",
            side_effect=OSError("simulated IO error"),
        ),
        patch("fleet_platform.workers.ansible_tasks.secrets.token_urlsafe", return_value="FAKE_TOKEN"),
        patch("fleet_platform.workers.ansible_tasks.hash_password", return_value="hashed"),
    ):
        try:
            bootstrap_node(node_id=str(node_id), target_ip="10.0.0.1")
        except Exception:
            pass

    assert node.bootstrap_error, "bootstrap_error must be a non-empty string after an exception — got empty/None"


def test_no_permission_error_when_pillar_dir_missing():
    """bootstrap_node must not raise PermissionError/FileNotFoundError due to pillar dir access."""
    from fleet_platform.workers.ansible_tasks import bootstrap_node

    node_id = uuid.uuid4()
    node = _make_node(node_id)

    fake_thread, fake_runner = _make_run_async(status="successful", rc=0)

    def fake_get_sync_db():
        run_row = MagicMock()
        run_row.id = uuid.uuid4()
        run_row.status = "running"
        run_row.finished_at = None

        session = MagicMock()

        def execute_side_effect(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = node
            result.scalar_one.return_value = node
            result.scalars.return_value.first.return_value = None  # no SaltMaster row
            return result

        session.execute.side_effect = execute_side_effect
        session.add = MagicMock()
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=session)
        ctx.__exit__ = MagicMock(return_value=False)
        return ctx

    raised: list[Exception] = []

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", side_effect=fake_get_sync_db),
        patch(
            "fleet_platform.workers.ansible_tasks._get_bootstrap_settings",
            return_value=("admin", "pw", "pubkey"),
        ),
        patch(
            "fleet_platform.workers.ansible_tasks.resolve_node_credentials_sync",
            return_value={
                "ssh_user": "admin",
                "ssh_password": "pw",
                "ssh_key": "",
                "auth_mode": "password",
                "credential_source": "node",
            },
        ),
        patch(
            "fleet_platform.workers.ansible_tasks.ansible_runner.run_async",
            return_value=(fake_thread, fake_runner),
        ),
        patch("fleet_platform.workers.ansible_tasks.secrets.token_urlsafe", return_value="FAKE_TOKEN"),
        patch("fleet_platform.workers.ansible_tasks.hash_password", return_value="hashed"),
    ):
        try:
            bootstrap_node(node_id=str(node_id), target_ip="10.0.0.1")
        except (PermissionError, FileNotFoundError) as exc:
            raised.append(exc)
        except Exception:
            pass  # other exceptions (e.g. from missing real paths) are OK for this test

    assert not raised, f"bootstrap_node raised a filesystem error that is likely from pillar dir access: {raised}"
