"""Tests for intent classifier: conceptual questions must not route to code-gen (#670)."""

import pytest

from fleet_platform.services.llm_intent import classify_intent

# ---------------------------------------------------------------------------
# Previously misrouted: conceptual / explanatory questions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prompt",
    [
        # "how does X work" family — were caught by \bhow does\b but only partially
        "how does a playbook work",
        "how does salt state work",
        "how does ansible handle roles",
        # bare noun conceptual questions that used to route via \bplaybook\b
        "what is a playbook",
        "what is a salt state",
        "what is ansible",
        "what are salt states",
        "what are playbooks used for",
        # "how do I understand X" family
        "how do I understand salt states",
        "how do playbooks work",
        # "tell me about" family
        "tell me about ansible",
        "tell me about salt states",
        # "can you explain" family
        "can you explain what a playbook does",
        "can you explain how salt works",
        # why/describe family
        "why does salt use states",
        "why do playbooks have roles",
        "describe the purpose of a salt state",
    ],
)
def test_conceptual_question_routes_to_explain_not_code_gen(prompt):
    """The specific misrouting case from #670: conceptual questions must go to explain."""
    result = classify_intent(prompt)
    assert result == "explain", f"Conceptual prompt {prompt!r} routed to {result!r} instead of 'explain'"


# ---------------------------------------------------------------------------
# Regression: genuine code-gen prompts must still route correctly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prompt,expected",
    [
        ("write a salt state to install homebrew", "salt_state"),
        ("generate a sls file for nginx", "salt_state"),
        ("create a salt state for redis", "salt_state"),
        ("write an ansible playbook for ssh hardening", "ansible_playbook"),
        ("generate a playbook to restart all nodes", "ansible_playbook"),
        ("create an ansible playbook with roles and handlers", "ansible_playbook"),
        ("run salt cmd.run on mm1", "fleet_command"),
        ("execute disk.usage on all nodes", "fleet_command"),
        ("salt '*' test.ping", "fleet_command"),
        ("how many nodes are online?", "fleet_query"),
        ("what is the status of mm2?", "fleet_query"),  # live data query → fleet_query
        ("hi there", "fleet_query"),
    ],
)
def test_code_gen_and_other_intents_still_route_correctly(prompt, expected):
    result = classify_intent(prompt)
    assert result == expected, f"For {prompt!r}: got {result!r}, want {expected!r}"


# ---------------------------------------------------------------------------
# Existing tests remain passing (regression guard)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prompt,expected",
    [
        ("generate a salt state to install homebrew", "salt_state"),
        ("write a sls file for nginx", "salt_state"),
        ("create an ansible playbook to restart the minion", "ansible_playbook"),
        ("write a yaml playbook for all nodes", "ansible_playbook"),
        ("run salt cmd.run on mm1", "fleet_command"),
        ("execute disk.usage on all nodes", "fleet_command"),
        ("how many nodes are online?", "fleet_query"),
        ("explain this state file", "explain"),
        ("what does this yaml do", "explain"),
        ("hi there", "fleet_query"),
    ],
)
def test_existing_cases_unchanged(prompt, expected):
    result = classify_intent(prompt)
    assert result == expected, f"Regression: {prompt!r} → {result!r}, want {expected!r}"


def test_bare_playbook_noun_routes_to_explain_not_ansible():
    """Core misrouting case from #670: 'playbook' alone must not trigger ansible_playbook."""
    assert classify_intent("what is a playbook") == "explain"
    assert classify_intent("how does a playbook work") == "explain"


def test_bare_salt_state_noun_routes_to_explain_not_salt_state():
    """Bare 'salt state' noun without a generation verb must not trigger salt_state."""
    assert classify_intent("what is a salt state") == "explain"
    assert classify_intent("how does a salt state work") == "explain"


def test_how_to_understand_routes_to_explain():
    assert classify_intent("how do I understand the pillar system") == "explain"
    assert classify_intent("how can I learn about salt modules") == "explain"
