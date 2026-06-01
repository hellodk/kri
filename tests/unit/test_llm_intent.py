"""Unit tests for the heuristic intent classifier."""
import pytest


@pytest.mark.parametrize("prompt,expected", [
    ("generate a salt state to install homebrew", "salt_state"),
    ("write a sls file for nginx", "salt_state"),
    ("create an ansible playbook to restart the minion", "ansible_playbook"),
    ("write a yaml playbook for all nodes", "ansible_playbook"),
    ("run salt cmd.run on mm1", "fleet_command"),
    ("execute disk.usage on all nodes", "fleet_command"),
    ("how many nodes are online?", "fleet_query"),
    ("what is the status of mm2?", "fleet_query"),
    ("explain this state file", "explain"),
    ("what does this yaml do", "explain"),
    ("hi there", "fleet_query"),  # default fallback
])
def test_intent_classifier(prompt, expected):
    from fleet_platform.services.llm_intent import classify_intent
    result = classify_intent(prompt)
    assert result == expected, f"For '{prompt}': got {result!r}, want {expected!r}"


def test_auto_constant_exported():
    from fleet_platform.services.llm_intent import AUTO_INTENT
    assert AUTO_INTENT == "auto"


def test_classify_intent_returns_string():
    from fleet_platform.services.llm_intent import classify_intent
    result = classify_intent("anything at all")
    assert isinstance(result, str)


def test_salt_state_variations():
    from fleet_platform.services.llm_intent import classify_intent
    assert classify_intent("write a salt state for redis") == "salt_state"
    assert classify_intent("generate sls for postgresql") == "salt_state"


def test_ansible_playbook_variations():
    from fleet_platform.services.llm_intent import classify_intent
    assert classify_intent("write an ansible playbook") == "ansible_playbook"
    assert classify_intent("create a playbook for ssh hardening") == "ansible_playbook"
