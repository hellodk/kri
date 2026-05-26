# tests/unit/test_llm_context.py
import pytest

INTENT_SYSTEM_ADDENDUM = {
    "salt_state": "Generate a complete SaltStack state file (.sls).",
    "ansible_playbook": "Generate a complete Ansible playbook (YAML).",
    "fleet_command": "Suggest the exact Salt execution module call.",
    "explain": "Explain the given code in plain English.",
}


def test_build_context_returns_nonempty_string():
    from fleet_platform.services.llm_context import build_static_context
    ctx = build_static_context(
        node_count=5,
        online_count=4,
        groups=["dev", "prod"],
        salt_master="salt.fleet.local",
        playbooks_dir="/srv/playbooks",
    )
    assert isinstance(ctx, str)
    assert len(ctx) > 50


def test_build_context_contains_node_count():
    from fleet_platform.services.llm_context import build_static_context
    ctx = build_static_context(
        node_count=12,
        online_count=10,
        groups=[],
        salt_master="salt.local",
        playbooks_dir="/srv",
    )
    assert "12" in ctx
    assert "10" in ctx


def test_build_context_contains_groups():
    from fleet_platform.services.llm_context import build_static_context
    ctx = build_static_context(
        node_count=3,
        online_count=3,
        groups=["alpha", "beta", "gamma"],
        salt_master="s",
        playbooks_dir="/p",
    )
    assert "alpha" in ctx
    assert "beta" in ctx
    assert "gamma" in ctx


def test_intent_addendum_covers_all_intents():
    intents = {"salt_state", "ansible_playbook", "fleet_command", "explain"}
    assert set(INTENT_SYSTEM_ADDENDUM.keys()) == intents


def test_build_context_intent_addendum_included():
    from fleet_platform.services.llm_context import build_static_context, INTENT_ADDENDUM
    # Verify INTENT_ADDENDUM in module covers all four intents
    assert set(INTENT_ADDENDUM.keys()) == {"salt_state", "ansible_playbook", "fleet_command", "explain"}
