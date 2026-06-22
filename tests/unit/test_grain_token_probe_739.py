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


def test_collect_grains_no_pillar_error_branch_is_gone():
    """The dead 'no node_token found in pillar' branch must be removed (#739)."""
    import inspect

    import fleet_platform.workers.ansible_tasks as mod

    source = inspect.getsource(mod.collect_node_grains)
    assert "no node_token found in pillar" not in source, (
        "Dead pillar-error branch still present in collect_node_grains — fix #739 not applied"
    )


def test_collect_grains_no_pillar_file_read():
    """pillar_file.exists() / pillar_file.read_text() must never be called (#739)."""
    import inspect

    import fleet_platform.workers.ansible_tasks as mod

    source = inspect.getsource(mod.collect_node_grains)
    assert "pillar_file.exists()" not in source, (
        "pillar_file.exists() still present — dead pillar read not removed (#739)"
    )


# ---------------------------------------------------------------------------
# #738 — asyncio.run(run_probe()) must execute OUTSIDE get_sync_db() context
# ---------------------------------------------------------------------------


def _is_inside_with_get_sync_db(lines: list[str], target_idx: int) -> bool:
    """Return True if the line at target_idx is nested inside a `with get_sync_db()` block."""
    target_indent = len(lines[target_idx]) - len(lines[target_idx].lstrip())
    current_min_indent = target_indent
    for j in range(target_idx - 1, -1, -1):
        src_line = lines[j]
        stripped = src_line.lstrip()
        if not stripped:
            continue
        line_indent = len(src_line) - len(stripped)
        if line_indent >= current_min_indent:
            # Same or deeper indent — sibling/child, not an enclosing block
            continue
        # First ancestor line at lower indent — is it a DB context?
        if "with get_sync_db()" in src_line:
            return True
        # Update threshold to continue scanning for even higher ancestors
        current_min_indent = line_indent
    return False


def test_provision_master_probe_runs_outside_db_session():
    """asyncio.run(run_probe()) must be called AFTER get_sync_db context exits (#738).

    Holding the DB session open during network I/O exhausts the sync pool under load.
    The fix: read master attrs inside the `with` block, expunge/copy the object, exit
    the block, then call asyncio.run(run_probe()) outside.
    """
    import inspect

    import fleet_platform.workers.ansible_tasks as mod

    source = inspect.getsource(mod.provision_master)
    lines = source.splitlines()

    probe_lines = [(i, line) for i, line in enumerate(lines) if "asyncio.run(run_probe" in line]
    assert probe_lines, "asyncio.run(run_probe()) not found in provision_master — check function name"

    for probe_idx, probe_line_text in probe_lines:
        inside = _is_inside_with_get_sync_db(lines, probe_idx)
        assert not inside, (
            f"asyncio.run(run_probe()) at source line {probe_idx!r} is still nested inside "
            "a `with get_sync_db()` block — DB session is held during probe I/O (#738 not fixed).\n"
            f"Line: {probe_line_text.strip()!r}"
        )


def test_provision_master_probe_db_session_released_before_probe():
    """Structural test: the DB context must close before run_probe is called (#738).

    We verify that after the fix the code reads master fields, exits `with get_sync_db()`,
    and only then invokes asyncio.run(run_probe()).
    """
    import inspect

    import fleet_platform.workers.ansible_tasks as mod

    source = inspect.getsource(mod.provision_master)
    lines = source.splitlines()

    # The probe call must exist
    probe_indices = [i for i, src_line in enumerate(lines) if "asyncio.run(run_probe" in src_line]
    assert probe_indices, "asyncio.run(run_probe()) missing from provision_master"

    # There must be a `with get_sync_db()` block BEFORE the probe that closes before it
    # (i.e., at the same or lower indentation as the probe call, and appearing earlier)
    for probe_idx in probe_indices:
        probe_indent = len(lines[probe_idx]) - len(lines[probe_idx].lstrip())

        # Scan backwards for ANY `with get_sync_db()` at lower indent than the probe
        # (meaning the probe must be OUTSIDE all DB contexts)
        assert not _is_inside_with_get_sync_db(lines, probe_idx), (
            "run_probe() still called inside an open DB session (#738)"
        )

        # Scan forward to confirm the probe line exists after the DB `with` block closes
        # by checking that we can find a prior `with get_sync_db()` block at equal/lower indent
        # that was opened and closed before this index
        found_prior_db_open = False
        for j in range(0, probe_idx):
            src_line = lines[j]
            stripped = src_line.lstrip()
            if not stripped:
                continue
            line_indent = len(src_line) - len(stripped)
            if "with get_sync_db()" in src_line and line_indent <= probe_indent:
                found_prior_db_open = True
                break
        assert found_prior_db_open, (
            "No prior `with get_sync_db()` block found before the probe call — check provision_master structure"
        )
