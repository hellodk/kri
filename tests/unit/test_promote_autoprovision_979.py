"""Issue #979 — promote_node_to_master auto-provisions the new master.

Previously promote created an 'unprovisioned' SaltMaster row and stopped, so the
promoted node did nothing. Now the promote handler enqueues provision_master and
flips provision_status to 'provisioning'. Source-inspection style (mirrors the
repo's route-wiring tests; the async handler + DB are exercised in integration).
"""

from pathlib import Path

_SRC = (
    Path(__file__).resolve().parents[2] / "fleet_platform" / "api" / "routes" / "salt_masters.py"
).read_text()


def _promote_body() -> str:
    # Slice from the promote handler to the next @router decorator after it.
    start = _SRC.index("async def promote_node_to_master")
    tail = _SRC[start:]
    nxt = tail.index("@router", 1)
    return tail[:nxt]


def test_promote_enqueues_provision_master():
    body = _promote_body()
    assert "fleet_platform.workers.ansible_tasks.provision_master" in body
    assert "send_task" in body
    assert '"install"' in body


def test_promote_sets_provisioning_status():
    body = _promote_body()
    assert 'provision_status = "provisioning"' in body


def test_promote_still_creates_master_row():
    body = _promote_body()
    assert "db.add(master)" in body
    assert "SaltMasterResponse.model_validate(master)" in body
