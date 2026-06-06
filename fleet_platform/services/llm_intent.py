"""Heuristic intent classifier for the LLM Fleet Assistant.

Routes the user prompt to one of the five supported intents.
Design: keyword/regex rules first (fast, deterministic, transparent).
Upgrade path: replace with a small classifier model (distilbert) in Wave 3.
"""

import re

AUTO_INTENT = "auto"

# Each rule is (intent, [regex patterns]).
# Checked in order — first match wins.
_INTENT_RULES: list[tuple[str, list[str]]] = [
    (
        "salt_state",
        [
            r"\b(write|generate|create)\b.{0,50}\b(state|sls|salt)\b",
            r"\bsalt\s+state\b",
            r"\bsls\b",
            r"\b\.sls\b",
            r"\bsalt\s+(file|module)\b",
        ],
    ),
    (
        "ansible_playbook",
        [
            r"\b(write|generate|create)\b.{0,50}\b(playbook|ansible|yaml)\b",
            r"\bansible\b",
            r"\bplaybook\b",
            r"\b(roles|tasks|handlers)\b",
        ],
    ),
    (
        "fleet_command",
        [
            r"\b(run|execute)\b.{0,40}\b(salt|cmd\.run|module|function)\b",
            r"\bsalt\s+['\*]",
            r"\b(disk\.|status\.|pkg\.|service\.)\w+",
            r"\bsalt\b.{0,30}\b(cmd\.run|test\.ping|state\.apply)\b",
        ],
    ),
    (
        "explain",
        [
            r"\bexplain\b",
            r"\bwhat does\b",
            r"\bhow does\b",
            r"\bwhat is this\b",
            r"\bdescribe this\b",
        ],
    ),
]

_DEFAULT_INTENT = "fleet_query"


def classify_intent(prompt: str) -> str:
    """Return the intent string for the given prompt.

    Checks rules in order: salt_state, ansible_playbook, fleet_command,
    explain. Falls back to fleet_query (the safe default).
    """
    lowered = prompt.lower()
    for intent, patterns in _INTENT_RULES:
        for pat in patterns:
            if re.search(pat, lowered):
                return intent
    return _DEFAULT_INTENT
