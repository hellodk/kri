# tests/unit/test_grain_token_probe_739.py
"""Regression tests for issues #739 and #738.

#739 (High) — collect_node_grains reads a pillar file that is never populated.
  Fix: stop reading the pillar file; mint a fresh token, persist its hash to
  node.node_token_hash, and send the plaintext token in X-Node-Token.

#738 (High) — sync DB session held open during asyncio.run(run_probe()) I/O
  in provision_master, exhausting the pool under load.
  Fix: close the DB session before calling asyncio.run(run_probe()).

Run: pytest tests/unit/test_grain_token_probe_739.py -q
Do NOT run the full pytest tests/unit/ suite — that is the merge gate.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_node(minion_id: str = "testminion") -> MagicMock:
    node = MagicMock()
    node.bootstrap_ip = "10.0.0.1"
    node.minion_id = minion_id
    node.ssh_host_key = None
    node.node_token_hash = ""
    return node


def _make_db_ctx(node, setting_row=None):
    """Return a mock get_sync_db() context that yields node + optional setting row."""
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.side_effect = [node, setting_row]
    db = MagicMock()
    db.execute.return_value = scalar_result
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=db)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _make_urlopen_ok():
    resp = MagicMock()
    resp.status = 200
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=resp)
    cm.__exit__ = MagicMock(return_value=False)
    return cm


MASTER_CREDS = {
    "api_url": "https://salt.local:4507",
    "api_user": "krisalt",
    "api_password": "pw",
    "api_eauth": "pam",
    "tls_verify": False,
}


# ---------------------------------------------------------------------------
# #739 — pillar file must NOT be read; fresh token must be minted
# ---------------------------------------------------------------------------


def test_collect_grains_succeeds_without_pillar_file(tmp_path):
    """No pillar file present must NOT cause an error — pillar reading was removed (#739)."""
    import fleet_platform.workers.ansible_tasks as mod

    node = _make_node()
    ctx = _make_db_ctx(node)

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", return_value=ctx),
        patch("fleet_platform.workers.ansible_tasks._get_node_credentials", return_value=("admin", None, "password")),
        patch("fleet_platform.workers.ansible_tasks._get_pillar_dir", return_value=tmp_path),
        patch("fleet_platform.workers.ansible_tasks._resolve_node_master_creds", return_value=MASTER_CREDS),
        patch("fleet_platform.workers.ansible_tasks._grains_via_salt_api", return_value=({"os": "Linux"}, None)),
        patch("fleet_platform.workers.ansible_tasks.hash_password", return_value="$fake-hash$"),
        patch("urllib.request.urlopen", return_value=_make_urlopen_ok()),
    ):
        # tmp_path has NO pillar file — previously this triggered "no node_token found in pillar"
        result = mod.collect_node_grains.run(str(uuid.uuid4()))

    assert result["status"] == "ok", f"Expected ok, got: {result}"


def test_collect_grains_mints_fresh_token_and_persists_hash(tmp_path):
    """A fresh plaintext token is minted; its hash is saved to node.node_token_hash (#739)."""
    import fleet_platform.workers.ansible_tasks as mod

    node = _make_node()
    ctx = _make_db_ctx(node)

    captured_requests: list = []

    def fake_urlopen(req, timeout=None):
        captured_requests.append(req)
        return _make_urlopen_ok()

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", return_value=ctx),
        patch("fleet_platform.workers.ansible_tasks._get_node_credentials", return_value=("admin", None, "password")),
        patch("fleet_platform.workers.ansible_tasks._get_pillar_dir", return_value=tmp_path),
        patch("fleet_platform.workers.ansible_tasks._resolve_node_master_creds", return_value=MASTER_CREDS),
        patch("fleet_platform.workers.ansible_tasks._grains_via_salt_api", return_value=({"os": "Linux"}, None)),
        patch("urllib.request.urlopen", side_effect=fake_urlopen),
    ):
        result = mod.collect_node_grains.run(str(uuid.uuid4()))

    assert result["status"] == "ok", f"Expected ok, got: {result}"

    # node_token_hash must have been updated (no longer empty)
    assert node.node_token_hash != "", "node.node_token_hash was never set — fresh token not persisted"

    # DB commit must have been called to save the hash
    db = ctx.__enter__.return_value
    db.commit.assert_called()

    # X-Node-Token header must be present in the ingest POST
    assert len(captured_requests) == 1, "Expected exactly one HTTP POST to ingest"
    sent_token = captured_requests[0].get_header("X-node-token")
    assert sent_token, "X-Node-Token header is missing from ingest POST"

    # The plaintext token sent in the header must match the hash stored on node
    from fleet_platform.services.node_status import verify_node_token

    assert verify_node_token(sent_token, node.node_token_hash), (
        "Plaintext token in X-Node-Token does not verify against node.node_token_hash — "
        "the wrong token was sent or the hash was not persisted correctly"
    )


def test_collect_grains_no_pillar_error_branch_is_gone(tmp_path):
    """Missing pillar file must NOT trigger the old 'no node_token found in pillar' error (#739).

    If the dead branch were still present, an empty pillar dir would raise a RuntimeError
    or return an error dict with a pillar-related message. The fix ensures the call succeeds.
    """
    import fleet_platform.workers.ansible_tasks as mod

    node = _make_node()
    ctx = _make_db_ctx(node)

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", return_value=ctx),
        patch("fleet_platform.workers.ansible_tasks._get_node_credentials", return_value=("admin", None, "password")),
        patch("fleet_platform.workers.ansible_tasks._get_pillar_dir", return_value=tmp_path),
        patch("fleet_platform.workers.ansible_tasks._resolve_node_master_creds", return_value=MASTER_CREDS),
        patch("fleet_platform.workers.ansible_tasks._grains_via_salt_api", return_value=({"os": "Linux"}, None)),
        patch("fleet_platform.workers.ansible_tasks.hash_password", return_value="$fake-hash$"),
        patch("urllib.request.urlopen", return_value=_make_urlopen_ok()),
    ):
        result = mod.collect_node_grains.run(str(uuid.uuid4()))

    assert result["status"] == "ok", f"Dead pillar-error branch may still be present — expected ok, got: {result}"
    assert "pillar" not in str(result).lower(), (
        f"Pillar error message leaked into result — dead branch not fully removed: {result}"
    )


def test_collect_grains_no_pillar_file_read(tmp_path):
    """collect_node_grains must NOT attempt to read a pillar file (#739).

    The old implementation called pillar_file.exists() and pillar_file.read_text().
    The fix replaces this with a freshly minted token. We verify by confirming
    the call succeeds even when the pillar directory is completely empty.
    """
    import fleet_platform.workers.ansible_tasks as mod

    node = _make_node()
    ctx = _make_db_ctx(node)

    # tmp_path is an empty directory — no pillar file at any expected path.
    # If pillar_file.exists() / read_text() were still called, and the code treated
    # a missing file as an error, the result would not be "ok".
    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", return_value=ctx),
        patch("fleet_platform.workers.ansible_tasks._get_node_credentials", return_value=("admin", None, "password")),
        patch("fleet_platform.workers.ansible_tasks._get_pillar_dir", return_value=tmp_path),
        patch("fleet_platform.workers.ansible_tasks._resolve_node_master_creds", return_value=MASTER_CREDS),
        patch("fleet_platform.workers.ansible_tasks._grains_via_salt_api", return_value=({"os": "Linux"}, None)),
        patch("fleet_platform.workers.ansible_tasks.hash_password", return_value="$fake-hash$"),
        patch("urllib.request.urlopen", return_value=_make_urlopen_ok()),
    ):
        result = mod.collect_node_grains.run(str(uuid.uuid4()))

    assert result["status"] == "ok", (
        f"pillar_file.exists() may still be called — expected ok with empty pillar dir, got: {result}"
    )


# ---------------------------------------------------------------------------
# #738 — asyncio.run(run_probe()) must execute OUTSIDE get_sync_db() context
# ---------------------------------------------------------------------------


def _run_provision_master_with_logging(master_uuid):
    """Drive provision_master through the success path, logging the relative order of
    get_sync_db() context exits and the run_probe() network call.

    Returns the ordered call_log so callers can assert that the probe runs only after
    the DB session has been released (#738).

    `run_probe` is imported locally inside provision_master via
    `from fleet_platform.services.salt_master_probe import run_probe`, so patching it at
    its source module captures the real `asyncio.run(run_probe(...))` invocation without
    having to patch the locally-imported `asyncio`.
    """
    import fleet_platform.workers.ansible_tasks as mod

    call_log: list[str] = []

    master_mock = MagicMock()
    master_mock.id = master_uuid
    master_mock.ssh_host = "10.0.0.1"
    master_mock.address = "10.0.0.1"
    master_mock.ssh_user = "admin"
    master_mock.ssh_key_enc = None
    master_mock.ssh_password_enc = None
    master_mock.api_password_enc = None
    master_mock.provision_status = "provisioning"

    db_call_count = [0]

    def make_ctx(label: str):
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = master_mock
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=db)

        def on_exit(*args):
            call_log.append(f"db_exit:{label}")
            return False

        ctx.__exit__ = MagicMock(side_effect=on_exit)
        return ctx

    def fake_get_sync_db():
        idx = db_call_count[0]
        db_call_count[0] += 1
        labels = ["init", "probe", "final"]
        label = labels[idx] if idx < len(labels) else f"extra_{idx}"
        return make_ctx(label)

    async def fake_run_probe(master):
        call_log.append("run_probe")
        return {"status": "online", "checks": []}

    mock_thread = MagicMock()
    mock_thread.is_alive.return_value = False
    mock_runner = MagicMock()
    mock_runner.status = "successful"
    mock_runner.rc = 0

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", side_effect=fake_get_sync_db),
        patch("fleet_platform.workers.ansible_tasks.ansible_runner") as mock_ar,
        patch("fleet_platform.workers.ansible_tasks._detect_os_family", return_value="Linux"),
        patch("fleet_platform.workers.ansible_tasks._get_bootstrap_settings", return_value=("admin", None, None)),
        patch("fleet_platform.services.salt_master_probe.run_probe", side_effect=fake_run_probe),
    ):
        mock_ar.run_async.return_value = (mock_thread, mock_runner)
        mod.provision_master.run(str(master_uuid))

    return call_log


def test_provision_master_probe_runs_outside_db_session():
    """run_probe() must run AFTER the probe get_sync_db context exits (#738).

    Holding the DB session open during network I/O exhausts the sync pool under load.
    The fix: read master attrs inside the `with` block, expunge/copy the object, exit
    the block, then call asyncio.run(run_probe()) outside.
    """
    call_log = _run_provision_master_with_logging(uuid.uuid4())

    assert "run_probe" in call_log, f"run_probe() was never called — call order: {call_log}"

    probe_exit_idx = next((i for i, e in enumerate(call_log) if e == "db_exit:probe"), None)
    run_probe_idx = call_log.index("run_probe")
    assert probe_exit_idx is not None, f"Probe DB context exit not found — call order: {call_log}"
    assert probe_exit_idx < run_probe_idx, (
        f"run_probe() ran while the probe DB session was still open (#738). call order: {call_log}"
    )


def test_provision_master_probe_db_session_released_before_probe():
    """A get_sync_db() context must open and close BEFORE run_probe() runs (#738).

    We verify that after the fix the code reads master fields, exits `with get_sync_db()`,
    and only then invokes asyncio.run(run_probe()).
    """
    call_log = _run_provision_master_with_logging(uuid.uuid4())

    assert "run_probe" in call_log, f"run_probe() was never called — call order: {call_log}"
    run_probe_idx = call_log.index("run_probe")

    db_exits_before_probe = [e for e in call_log[:run_probe_idx] if e.startswith("db_exit:")]
    assert db_exits_before_probe, (
        f"No DB context exited before run_probe() — session still held during network I/O (#738). "
        f"call order: {call_log}"
    )
