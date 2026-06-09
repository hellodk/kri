# tests/unit/test_llm_grounding_637.py
"""
Tests for #637 Fix 1 — grounding rules deflect to the UI removed.
"""

from fleet_platform.services.llm_context import _GROUNDING_RULES, build_static_context


def test_grounding_rules_no_kri_ui_deflection():
    """_GROUNDING_RULES must NOT deflect operators to the kri UI as a fallback answer.

    The old 3rd rule read 'tell the operator where to find it in the kri UI' — this
    caused the model to deflect for data it already had.  The new rule prohibits that
    deflection.  We check the old positive-deflection phrase is gone.
    """
    assert "find it in the kri UI" not in _GROUNDING_RULES
    assert "where to find it" not in _GROUNDING_RULES


def test_grounding_rules_contains_authoritative():
    """_GROUNDING_RULES must assert the data is authoritative."""
    assert "authoritative" in _GROUNDING_RULES.lower()


def test_grounding_rules_contains_hostname():
    """_GROUNDING_RULES must reference hostname as the node's name."""
    assert "hostname" in _GROUNDING_RULES


def test_build_static_context_authoritative_label_present():
    """build_static_context output contains the 'authoritative node records' intro line."""
    ctx = build_static_context(
        node_count=1,
        online_count=1,
        groups=[],
        salt_master="",
        playbooks_dir="",
        node_records=[
            {
                "hostname": "192.168.1.10",
                "minion_id": "mm",
                "ip": "—",
                "status": "online",
                "last_seen": "2m ago",
                "group": "—",
            }
        ],
    )
    assert "authoritative node records" in ctx


def test_build_static_context_ip_hostname_present():
    """An IP-looking hostname is included verbatim in the node table."""
    ctx = build_static_context(
        node_count=1,
        online_count=1,
        groups=[],
        salt_master="",
        playbooks_dir="",
        node_records=[
            {
                "hostname": "192.168.1.10",
                "minion_id": "mm",
                "ip": "—",
                "status": "online",
                "last_seen": "2m ago",
                "group": "—",
            }
        ],
    )
    assert "192.168.1.10" in ctx
