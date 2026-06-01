"""Tests for #306 (prompt injection) and #307 (bulk settings)."""
from fleet_platform.services.llm_context import _sanitize_cell, build_static_context


def test_sanitize_cell_escapes_pipe():
    result = _sanitize_cell("host | inject")
    # Pipes should be escaped, not removed
    assert "\\|" in result
    # The text around the pipe should be preserved
    assert "host" in result and "inject" in result


def test_sanitize_cell_strips_newlines():
    assert "\n" not in _sanitize_cell("host\n## Rules")
    assert "\r" not in _sanitize_cell("host\rinjection")


def test_node_hostname_injection_does_not_break_table():
    """Malicious hostname must not add extra Markdown table columns."""
    records = [{
        "hostname": "mm1 | bad | data | extra",
        "minion_id": "mm1",
        "ip": "10.0.0.1",
        "status": "online",
        "last_seen": "1m ago",
        "group": "prod",
    }]
    ctx = build_static_context(
        node_count=1, online_count=1,
        groups=["prod"], salt_master="s", playbooks_dir="/p",
        node_records=records,
    )
    # The hostname injection attempt should be escaped, preventing table breakage
    assert "mm1 \\|" in ctx, "Pipes in hostname must be escaped"
    # The escaped pipes should appear in the table, not create extra columns
    assert "mm1 \\| bad \\| data \\| extra" in ctx


def test_build_fleet_context_uses_bulk_settings():
    """build_fleet_context must call get_settings_bulk, not individual get_setting."""
    import inspect

    from fleet_platform.services.llm_context import build_fleet_context
    source = inspect.getsource(build_fleet_context)
    assert "get_settings_bulk" in source, "Must use get_settings_bulk for settings"
    # Count sequential get_setting calls — should be 0 for the 3 settings
    import re
    # Should not have bare 'await get_setting(db,' (individual calls)
    individual_calls = re.findall(r'await get_setting\(db,', source)
    assert len(individual_calls) == 0, (
        f"Found {len(individual_calls)} sequential get_setting() calls — use get_settings_bulk"
    )
