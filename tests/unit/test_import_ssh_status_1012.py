"""Issue #1012 — import validate probes SSH reachability per row (warn-only).

`import_validate` now probes each row with an IP via `probe_node_ssh` (bounded
concurrency) and stamps `ssh_state`/`ssh_detail` onto the response rows. A row
with no IP is stamped `unknown` without a probe. When the row's `reason` is
still empty and the probe did not return "ok", the probe detail backfills
`reason` so the existing Reason column in the UI shows the failure. Probing
never blocks or changes commit eligibility — `status`/`reason` classification
from `validate_row`/`dedup_rows` is otherwise untouched.

Run: pytest tests/unit/test_import_ssh_status_1012.py -q
Do NOT run the full pytest tests/unit/ suite — that is the merge gate, not the agent gate.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.routes.fleet import import_validate
from fleet_platform.schemas.node_import import ImportRow, ImportValidateRequest


def _canned_probe(node, creds, *, timeout=3):
    """Stand-in for probe_node_ssh: state keyed off the last IP octet."""
    ip = getattr(node, "ip_address", None) or ""
    if ip.endswith(".10"):
        return {"state": "ok", "detail": "authenticated"}
    if ip.endswith(".11"):
        return {"state": "auth_failed", "detail": "authentication rejected"}
    if ip.endswith(".12"):
        return {"state": "unreachable", "detail": "TCP port 22 closed or timed out"}
    return {"state": "unknown", "detail": "port 22 open; auth not verified (no stored credential)"}


def _mock_db():
    db = AsyncMock(spec=AsyncSession)
    res = MagicMock()
    res.all.return_value = []  # no existing nodes -> nothing is a duplicate
    db.execute.return_value = res
    return db


async def test_rows_get_ssh_state_and_detail_from_probe():
    payload = ImportValidateRequest(
        source="paste",
        text="mm-ok,mm-ok,192.168.1.10\nmm-auth,mm-auth,192.168.1.11\nmm-down,mm-down,192.168.1.12",
        ssh_username="admin",
        ssh_password="secret",
    )
    with patch("fleet_platform.api.routes.fleet.probe_node_ssh", side_effect=_canned_probe):
        resp = await import_validate(payload=payload, db=_mock_db(), _={"email": "test@example.com"})

    by_id = {r.minion_id: r for r in resp.rows}
    assert by_id["mm-ok"].ssh_state == "ok"
    assert by_id["mm-ok"].ssh_detail == "authenticated"

    assert by_id["mm-auth"].ssh_state == "auth_failed"
    assert by_id["mm-auth"].ssh_detail == "authentication rejected"


async def test_reason_backfilled_from_probe_detail_on_failure_only():
    payload = ImportValidateRequest(
        source="paste",
        text="mm-ok,mm-ok,192.168.1.10\nmm-down,mm-down,192.168.1.12",
    )
    with patch("fleet_platform.api.routes.fleet.probe_node_ssh", side_effect=_canned_probe):
        resp = await import_validate(payload=payload, db=_mock_db(), _={"email": "test@example.com"})

    by_id = {r.minion_id: r for r in resp.rows}
    # ok row: no probe failure, reason left as the classifier set it (empty for "new").
    assert by_id["mm-ok"].reason == ""
    # unreachable row: reason was empty from the classifier, backfilled from ssh_detail.
    assert by_id["mm-down"].reason == "TCP port 22 closed or timed out"


async def test_row_without_ip_is_unknown_and_not_probed():
    # parse_paste with a single bare token treats it as the IP itself, so a
    # truly IP-less row is built via CSV with an empty ip column instead.
    payload = ImportValidateRequest(
        source="csv",
        csv_content="minion_id,hostname,ip\nmm-no-ip,mm-no-ip,\n",
    )
    probe = MagicMock(side_effect=_canned_probe)
    with patch("fleet_platform.api.routes.fleet.probe_node_ssh", probe):
        resp = await import_validate(payload=payload, db=_mock_db(), _={"email": "test@example.com"})

    assert len(resp.rows) == 1
    row = resp.rows[0]
    assert row.minion_id == "mm-no-ip"
    assert row.ssh_state == "unknown"
    assert row.ssh_detail == "no IP"
    probe.assert_not_called()


async def test_import_row_and_validate_request_have_ssh_fields():
    """Contract test: schema carries the new SSH fields (#1012)."""
    row = ImportRow(minion_id="mm-1", ssh_state="ok", ssh_detail="authenticated")
    assert row.ssh_state == "ok"
    assert row.ssh_detail == "authenticated"

    row_default = ImportRow(minion_id="mm-2")
    assert row_default.ssh_state is None
    assert row_default.ssh_detail is None

    req = ImportValidateRequest(
        source="paste",
        ssh_username="admin",
        ssh_password="pw",
        ssh_key=None,
        ssh_auth_mode="password",
    )
    assert req.ssh_username == "admin"
    assert req.ssh_password == "pw"
    assert req.ssh_auth_mode == "password"
