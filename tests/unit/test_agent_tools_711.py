"""Unit tests for the read-only agent tools (#711).

These avoid all network/DB I/O: they exercise registry assembly, RBAC
filtering, schema hygiene, the dependency-free tools (lint_artifact), and the
Salt read-only allowlist guard with a stubbed platform setting.
"""

from __future__ import annotations

import pytest

from fleet_platform.agent import tools as agent_tools
from fleet_platform.agent.registry import ToolCtx
from fleet_platform.agent.tools import build_default_registry


def test_registry_has_expected_read_tools():
    reg = build_default_registry()
    names = {t.name for t in reg.all()}
    assert {
        "list_nodes",
        "get_node",
        "get_recent_audit",
        "read_playbook",
        "search_playbooks",
        "rag_search",
        "embed_text",
        "ping_node",
        "run_salt_cmd",
        "apply_salt_state_dry_run",
        "lint_artifact",
    } <= names


def test_rbac_filtering_is_monotonic():
    reg = build_default_registry()
    viewer = {t.name for t in reg.available_for_role("viewer")}
    operator = {t.name for t in reg.available_for_role("operator")}
    admin = {t.name for t in reg.available_for_role("admin")}
    # Higher roles see a superset.
    assert viewer <= operator <= admin
    assert "get_recent_audit" in admin and "get_recent_audit" not in operator
    assert "run_salt_cmd" in operator and "run_salt_cmd" not in viewer


def test_every_tool_has_handler_and_strict_schema():
    for spec in build_default_registry().all():
        assert spec.handler is not None, f"{spec.name} missing handler"
        assert spec.params_schema["type"] == "object"
        # All read-only tools must lock additionalProperties to reject junk args.
        assert spec.params_schema.get("additionalProperties") is False, spec.name
        # Phase B/D read + write-quarantine tools never gate on approval
        # (approval gating begins with Phase E live tools).
        assert spec.requires_approval is False
        assert spec.side_effect in ("read", "execute_read", "write_quarantine")


def test_node_to_dict_is_json_safe():
    class FakeNode:
        id = "11111111-1111-1111-1111-111111111111"
        minion_id = "mm7"
        hostname = "mac-mini-7"
        ip_address = None
        os_version = "14.5"
        status = "degraded"
        drift_score = 42
        cpu_usage_pct = 12.5
        mem_usage_pct = 60.0
        bootstrap_status = "registered"
        maintenance_mode = False
        last_seen_at = None

    d = agent_tools._node_to_dict(FakeNode())
    assert d["minion_id"] == "mm7"
    assert d["status"] == "degraded"
    assert d["ip_address"] is None
    assert d["last_seen_at"] is None


async def test_lint_artifact_valid_yaml():
    ctx = ToolCtx(actor="op@example.com", role="operator")
    out = await agent_tools._lint_artifact(ctx, content="- hosts: all\n  tasks: []\n")
    assert out["valid"] is True
    assert out["top_level_type"] == "list"
    assert out["warnings"] == []


async def test_lint_artifact_flags_play_without_hosts():
    ctx = ToolCtx(actor="op@example.com", role="operator")
    out = await agent_tools._lint_artifact(ctx, content="- name: no hosts here\n")
    assert out["valid"] is True
    assert any("hosts" in w for w in out["warnings"])


async def test_lint_artifact_invalid_yaml():
    ctx = ToolCtx(actor="op@example.com", role="operator")
    out = await agent_tools._lint_artifact(ctx, content="key: [unclosed\n")
    assert out["valid"] is False
    assert "error" in out


async def test_run_salt_cmd_rejects_non_readonly_function(monkeypatch):
    """A function outside the agent read-only subset must be refused before any
    Salt call — even if the platform allowlist would permit it."""

    async def _fake_get_setting(db, key):
        # Pretend the platform allows cmd.run (a mutating function).
        import json

        return json.dumps(["cmd.run", "test.ping"])

    monkeypatch.setattr("fleet_platform.services.platform_settings_svc.get_setting", _fake_get_setting)
    ctx = ToolCtx(actor="op@example.com", role="operator", db=object())
    with pytest.raises(ValueError, match="not permitted for the agent"):
        await agent_tools._run_salt_cmd(ctx, function="cmd.run", minion_id="mm7")


def test_agent_salt_readonly_excludes_mutating_functions():
    assert "cmd.run" not in agent_tools._AGENT_SALT_READONLY
    assert "state.apply" not in agent_tools._AGENT_SALT_READONLY
    assert "test.ping" in agent_tools._AGENT_SALT_READONLY


def test_registry_includes_phase_d_authoring_tools():
    names = {t.name for t in build_default_registry().all()}
    assert {"generate_ansible_playbook", "generate_salt_state", "dry_run_artifact"} <= names
    reg = build_default_registry()
    assert reg.get("generate_ansible_playbook").side_effect == "write_quarantine"
    assert reg.get("generate_salt_state").side_effect == "write_quarantine"


async def test_generate_ansible_playbook_writes_valid(tmp_path, monkeypatch):
    from fleet_platform.services import agent_quarantine as q

    monkeypatch.setattr(q, "QUARANTINE_ROOT", tmp_path)
    ctx = ToolCtx(actor="op@x.com", role="operator", session_id="sess1")
    out = await agent_tools._generate_ansible_playbook(
        ctx, filename="play.yml", content="- hosts: all\n  tasks:\n    - ansible.builtin.ping:\n"
    )
    assert out["written"] is True
    assert out["validation"]["valid"] is True
    assert out["artifact"]["filename"] == "play.yml"


async def test_generate_ansible_playbook_rejects_dangerous(tmp_path, monkeypatch):
    from fleet_platform.services import agent_quarantine as q

    monkeypatch.setattr(q, "QUARANTINE_ROOT", tmp_path)
    ctx = ToolCtx(actor="op@x.com", role="operator", session_id="sess1")
    out = await agent_tools._generate_ansible_playbook(
        ctx, filename="evil.yml", content="- hosts: all\n  tasks:\n    - ansible.builtin.shell: rm -rf /\n"
    )
    # Dangerous content is rejected and NEVER written to quarantine.
    assert out["written"] is False
    assert out["validation"]["valid"] is False
    assert q.list_artifacts("op@x.com", root=tmp_path) == []


async def test_dry_run_artifact_reports_plan(tmp_path, monkeypatch):
    from fleet_platform.services import agent_quarantine as q

    monkeypatch.setattr(q, "QUARANTINE_ROOT", tmp_path)
    ctx = ToolCtx(actor="op@x.com", role="operator", session_id="sess1")
    await agent_tools._generate_ansible_playbook(ctx, filename="play.yml", content="- hosts: all\n- hosts: db\n")
    out = await agent_tools._dry_run_artifact(ctx, filename="play.yml")
    assert out["validation"]["valid"] is True
    assert out["plan"] == {"plays": 2}
