# tests/unit/test_node_import.py
"""Unit tests for fleet_platform/services/node_import.py (#360)."""
import pytest

from fleet_platform.services.node_import import (
    dedup_rows,
    parse_csv,
    parse_paste,
    validate_row,
)

# ─── parse_paste ───────────────────────────────────────────────────────────────


def test_parse_paste_ip_only():
    """Single-field lines become minion_id=ip, hostname=ip."""
    rows = parse_paste("192.168.1.1")
    assert len(rows) == 1
    assert rows[0] == {"minion_id": "192.168.1.1", "hostname": "192.168.1.1", "ip": "192.168.1.1"}


def test_parse_paste_host_ip():
    """Two-field 'hostname,ip' line populates minion_id=hostname."""
    rows = parse_paste("mac-mini-01,192.168.1.10")
    assert len(rows) == 1
    r = rows[0]
    assert r["minion_id"] == "mac-mini-01"
    assert r["hostname"] == "mac-mini-01"
    assert r["ip"] == "192.168.1.10"


def test_parse_paste_three_cols():
    """Three-field line: minion_id, hostname, ip."""
    rows = parse_paste("mac-mini-01.local,mac-mini-01,10.0.0.5")
    assert len(rows) == 1
    r = rows[0]
    assert r["minion_id"] == "mac-mini-01.local"
    assert r["hostname"] == "mac-mini-01"
    assert r["ip"] == "10.0.0.5"


def test_parse_paste_blank_lines_skipped():
    """Blank and whitespace-only lines are skipped."""
    rows = parse_paste("\n\n  \n192.168.1.1\n  \n")
    assert len(rows) == 1


def test_parse_paste_comment_lines_skipped():
    """Lines starting with # are treated as comments and skipped."""
    text = "# This is a comment\n192.168.1.2\n# another comment\n10.0.0.1"
    rows = parse_paste(text)
    assert len(rows) == 2
    assert all(not r["minion_id"].startswith("#") for r in rows)


def test_parse_paste_multiple_rows():
    """Multiple valid rows are all returned."""
    text = "192.168.1.1\nhost-a,10.0.0.1\nhost-b.local,host-b,172.16.0.1"
    rows = parse_paste(text)
    assert len(rows) == 3


# ─── parse_csv ─────────────────────────────────────────────────────────────────


def test_parse_csv_default_headers():
    """CSV with default headers (minion_id,hostname,ip) parses correctly."""
    content = "minion_id,hostname,ip\nnode-01,node-01.local,192.168.1.10"
    rows = parse_csv(content)
    assert len(rows) == 1
    r = rows[0]
    assert r["minion_id"] == "node-01"
    assert r["hostname"] == "node-01.local"
    assert r["ip"] == "192.168.1.10"


def test_parse_csv_alt_column_names():
    """CSV with alternative column names (ip_address, host, id) is handled."""
    content = "id,host,ip_address\nminion-99,host99,10.10.10.1"
    rows = parse_csv(content)
    assert len(rows) == 1
    r = rows[0]
    assert r["minion_id"] == "minion-99"
    assert r["hostname"] == "host99"
    assert r["ip"] == "10.10.10.1"


def test_parse_csv_column_mapping():
    """Explicit mapping dict overrides automatic column name guessing."""
    content = "machine,address\nnode-x,172.16.0.5"
    rows = parse_csv(content, mapping={"minion_id": "machine", "ip": "address"})
    assert len(rows) == 1
    r = rows[0]
    assert r["minion_id"] == "node-x"
    assert r["ip"] == "172.16.0.5"


def test_parse_csv_includes_optional_fields():
    """CSV rows with group and ssh_user fields are captured."""
    content = "minion_id,hostname,ip,group,ssh_user\nnode-02,node-02,10.0.0.2,production,admin"
    rows = parse_csv(content)
    assert len(rows) == 1
    r = rows[0]
    assert r["group"] == "production"
    assert r["ssh_user"] == "admin"


def test_parse_csv_skips_empty_rows():
    """CSV rows with no ip and no hostname (truly empty) are skipped."""
    content = "minion_id,hostname,ip\n,,"
    rows = parse_csv(content)
    assert len(rows) == 0


# ─── validate_row ──────────────────────────────────────────────────────────────


def test_validate_row_new():
    """Valid row not in existing sets gets status 'new'."""
    row = {"minion_id": "node-01", "hostname": "node-01.local", "ip": "192.168.1.1"}
    result = validate_row(row, existing_minions=set(), existing_ips=set())
    assert result["status"] == "new"
    assert result["reason"] == ""


def test_validate_row_duplicate_minion():
    """Row whose minion_id is already in existing_minions gets status 'duplicate'."""
    row = {"minion_id": "node-01", "hostname": "node-01", "ip": "192.168.1.2"}
    result = validate_row(row, existing_minions={"node-01"}, existing_ips=set())
    assert result["status"] == "duplicate"
    assert "minion_id" in result["reason"]


def test_validate_row_duplicate_ip():
    """Row whose IP already exists in existing_ips gets status 'duplicate'."""
    row = {"minion_id": "node-02", "hostname": "node-02", "ip": "10.0.0.1"}
    result = validate_row(row, existing_minions=set(), existing_ips={"10.0.0.1"})
    assert result["status"] == "duplicate"
    assert "IP" in result["reason"]


def test_validate_row_invalid_ip():
    """Row with a non-IP in the ip field gets status 'invalid'."""
    row = {"minion_id": "node-03", "hostname": "node-03", "ip": "not-an-ip"}
    result = validate_row(row, existing_minions=set(), existing_ips=set())
    assert result["status"] == "invalid"
    assert "invalid IP" in result["reason"]


def test_validate_row_missing_minion_id():
    """Row with empty minion_id gets status 'invalid'."""
    row = {"minion_id": "", "hostname": "node-04", "ip": "192.168.1.4"}
    result = validate_row(row, existing_minions=set(), existing_ips=set())
    assert result["status"] == "invalid"
    assert "minion_id" in result["reason"]


def test_validate_row_invalid_hostname():
    """Row with a hostname that fails the regex gets status 'invalid'."""
    row = {"minion_id": "node-05", "hostname": "bad hostname!", "ip": "192.168.1.5"}
    result = validate_row(row, existing_minions=set(), existing_ips=set())
    assert result["status"] == "invalid"
    assert "hostname" in result["reason"]


def test_validate_row_no_ip_is_ok():
    """A row with no IP field at all is still valid (ip is optional)."""
    row = {"minion_id": "node-06", "hostname": "node-06", "ip": ""}
    result = validate_row(row, existing_minions=set(), existing_ips=set())
    assert result["status"] == "new"


# ─── dedup_rows ────────────────────────────────────────────────────────────────


def test_dedup_rows_intra_batch_by_minion():
    """Second row with same minion_id within the batch is marked 'duplicate'."""
    rows = [
        {"minion_id": "node-a", "ip": "10.0.0.1", "status": "new", "reason": ""},
        {"minion_id": "node-a", "ip": "10.0.0.2", "status": "new", "reason": ""},
    ]
    result = dedup_rows(rows)
    assert result[0]["status"] == "new"
    assert result[1]["status"] == "duplicate"
    assert "duplicate within import batch" in result[1]["reason"]


def test_dedup_rows_intra_batch_by_ip():
    """Second row with same IP within the batch is marked 'duplicate'."""
    rows = [
        {"minion_id": "node-b", "ip": "10.0.0.5", "status": "new", "reason": ""},
        {"minion_id": "node-c", "ip": "10.0.0.5", "status": "new", "reason": ""},
    ]
    result = dedup_rows(rows)
    assert result[0]["status"] == "new"
    assert result[1]["status"] == "duplicate"


def test_dedup_rows_already_invalid_not_touched():
    """Rows already marked 'invalid' are not altered by dedup_rows."""
    rows = [
        {"minion_id": "node-d", "ip": "bad-ip", "status": "invalid", "reason": "invalid IP: bad-ip"},
        {"minion_id": "node-d", "ip": "bad-ip", "status": "invalid", "reason": "invalid IP: bad-ip"},
    ]
    result = dedup_rows(rows)
    assert result[0]["status"] == "invalid"
    assert result[1]["status"] == "invalid"
