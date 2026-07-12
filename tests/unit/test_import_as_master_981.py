"""Issue #981 — bootstrap-as-master option in node import.

ImportCommitRequest gains as_master; when auto_bootstrap is on, import_commit
forwards it into queue_node_bootstrap so each imported+bootstrapped node is also
stood up as a salt-master (Phase A). Applies to every node (operator-confirmed).
"""

from pathlib import Path

from fleet_platform.schemas.node_import import ImportCommitRequest


def test_import_commit_request_has_as_master_default_false():
    req = ImportCommitRequest(rows=[])
    assert req.as_master is False


def test_import_commit_request_accepts_as_master():
    req = ImportCommitRequest(rows=[], auto_bootstrap=True, as_master=True)
    assert req.as_master is True


def test_import_commit_forwards_as_master_to_queue_bootstrap():
    src = (
        Path(__file__).resolve().parents[2] / "fleet_platform" / "api" / "routes" / "fleet.py"
    ).read_text()
    # The queue_node_bootstrap call inside import_commit must forward the flag.
    assert "as_master=payload.as_master" in src
