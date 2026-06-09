"""#633: _sanitize_cell must coerce non-str node cells (IPv4Address, datetime, int,
None) to str before sanitizing. A node `ip` arrives as an ipaddress.IPv4Address,
and calling .replace() on it raised AttributeError → every AI chat query 500'd in
build_fleet_context before the LLM was even called.
"""

import ipaddress
from datetime import datetime

from fleet_platform.services.llm_context import _sanitize_cell, build_static_context


def test_sanitize_cell_handles_ipv4address():
    assert _sanitize_cell(ipaddress.IPv4Address("192.168.1.10")) == "192.168.1.10"


def test_sanitize_cell_handles_non_str_types():
    assert _sanitize_cell(None) == "None"
    assert _sanitize_cell(42) == "42"
    # datetime str() must not raise
    assert isinstance(_sanitize_cell(datetime(2026, 6, 9, 4, 18, 0)), str)


def test_sanitize_cell_still_escapes_pipes_and_newlines():
    # pipe escaped, newline → space, carriage-return removed
    assert _sanitize_cell("a|b\nc\rd") == "a\\|b cd"


def test_build_static_context_with_ipv4address_ip_does_not_raise():
    node_records = [
        {
            "hostname": "mac-mini-1",
            "minion_id": "mac-mini-1",
            "ip": ipaddress.IPv4Address("192.168.1.10"),
            "status": "online",
            "last_seen": "2m ago",
            "group": "compute",
        }
    ]
    out = build_static_context(
        node_count=1,
        online_count=1,
        groups=["compute"],
        salt_master="mm1",
        playbooks_dir="/srv/playbooks",
        node_records=node_records,
    )
    assert "192.168.1.10" in out
    assert "mac-mini-1" in out
