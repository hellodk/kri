"""Heuristic intent classifier for the LLM Fleet Assistant.

Routes the user prompt to one of the five supported intents.
Design: keyword/regex rules first (fast, deterministic, transparent).
Upgrade path: replace with a small classifier model (distilbert) in Wave 3.

Rule ordering (#778):
  1. ``explain`` is checked first so "explain my ansible playbook" maps to
     explain, not ansible_playbook.
  2. Generation intents (salt_state, ansible_playbook) follow with anchored
     patterns so bare config-tool nouns don't trigger false positives.
  3. fleet_command catches operational invocations.
  4. fleet_query is the safe default.
"""

import re

AUTO_INTENT = "auto"

# Each rule is (intent, [regex patterns]).
# Checked in order — first match wins.
# IMPORTANT: explain must precede generation intents (#778).
_INTENT_RULES: list[tuple[str, list[str]]] = [
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
            r"\b(playbook|ansible)\b.{0,40}\b(roles|tasks|handlers|yaml)\b",
            r"\b(roles|tasks|handlers)\b.{0,40}\b(playbook|ansible)\b",
            r"\bplaybook\b",
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
]

_DEFAULT_INTENT = "fleet_query"


def classify_intent(prompt: str) -> str:
    """Return the intent string for the given prompt.

    Checks rules in order: explain, salt_state, ansible_playbook,
    fleet_command. Falls back to fleet_query (the safe default).
    The result is deterministic for a given prompt string.
    """
    lowered = prompt.lower()
    for intent, patterns in _INTENT_RULES:
        for pat in patterns:
            if re.search(pat, lowered):
                return intent
    return _DEFAULT_INTENT
