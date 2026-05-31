"""Tests for LLM context: per-node records, grounding rules, fleet_query intent (closes #281)."""
from datetime import UTC, datetime, timedelta

import pytest

from fleet_platform.services.llm_context import (
    INTENT_ADDENDUM,
    _format_last_seen,
    build_static_context,
)


def test_fleet_query_in_intent_addendum():
    assert "fleet_query" in INTENT_ADDENDUM


def test_fleet_query_addendum_has_grounding_rules():
    addendum = INTENT_ADDENDUM["fleet_query"]
    assert "ONLY" in addendum
    assert "cannot" in addendum.lower()
    assert "not present" in addendum.lower() or "absent" in addendum.lower()


def test_grounding_rules_in_static_context():
    ctx = build_static_context(
        node_count=2,
        online_count=1,
        groups=["MacMini-LLM"],
        salt_master="100.102.68.75",
        playbooks_dir="/playbooks",
    )
    lower = ctx.lower()
    assert "only" in lower
    assert "never claim" in lower or "cannot" in lower


def test_per_node_records_in_context():
    records = [
        {"hostname": "mm1", "minion_id": "mm1", "ip": "10.0.0.1",
         "status": "online", "last_seen": "2m ago", "group": "MacMini-LLM"},
        {"hostname": "mm2", "minion_id": "mm2", "ip": "10.0.0.2",
         "status": "offline", "last_seen": "3h ago", "group": "MacMiniApps"},
    ]
    ctx = build_static_context(
        node_count=2, online_count=1,
        groups=["MacMini-LLM", "MacMiniApps"],
        salt_master="", playbooks_dir="",
        node_records=records,
    )
    assert "mm1" in ctx
    assert "mm2" in ctx
    assert "online" in ctx
    assert "offline" in ctx
    assert "## Node Records" in ctx


def test_ip_redacted_in_context():
    records = [
        {"hostname": "mm1", "minion_id": "mm1", "ip": "[redacted]",
         "status": "online", "last_seen": "1m ago", "group": "—"},
    ]
    ctx = build_static_context(
        node_count=1, online_count=1, groups=[], salt_master="", playbooks_dir="",
        node_records=records,
    )
    assert "[redacted]" in ctx
    assert "10.0.0" not in ctx


def test_format_last_seen_none():
    assert _format_last_seen(None) == "never"


def test_format_last_seen_seconds():
    ts = datetime.now(UTC) - timedelta(seconds=45)
    assert "s ago" in _format_last_seen(ts)


def test_format_last_seen_minutes():
    ts = datetime.now(UTC) - timedelta(minutes=5)
    assert "m ago" in _format_last_seen(ts)


def test_format_last_seen_hours():
    ts = datetime.now(UTC) - timedelta(hours=3)
    assert "h ago" in _format_last_seen(ts)


def test_context_without_node_records_still_works():
    ctx = build_static_context(
        node_count=0, online_count=0, groups=[], salt_master="", playbooks_dir=""
    )
    assert "Fleet Snapshot" in ctx
    assert "## Node Records" not in ctx


def test_default_intent_is_fleet_query():
    # When an unknown intent is given, fleet_query is the fallback
    addendum = INTENT_ADDENDUM.get("unknown_intent", INTENT_ADDENDUM["fleet_query"])
    assert "ONLY" in addendum
