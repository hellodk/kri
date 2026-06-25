"""Heuristic intent classifier for the LLM Fleet Assistant.

Routes the user prompt to one of the five supported intents.
Design: keyword/regex rules first (fast, deterministic, transparent).
Upgrade path: replace with a small classifier model (distilbert) in Wave 3.

Rule ordering (#778, #670):
  1. ``explain`` is checked first so conceptual/explanatory questions ("how does
     X work", "what is a playbook", "why does salt use…") map to explain, not
     to a generation intent.  The explain patterns cover all common conceptual
     phrasings so bare config-tool nouns in later rules cannot steal them.
  2. Generation intents (salt_state, ansible_playbook) follow with anchored
     patterns that require an explicit generation verb (write/generate/create)
     so bare nouns like "playbook" or "salt state" no longer trigger code-gen
     on their own (#670).
  3. fleet_command catches operational invocations.
  4. fleet_query is the safe default.
"""

import re

AUTO_INTENT = "auto"

# Each rule is (intent, [regex patterns]).
# Checked in order — first match wins.
# IMPORTANT: explain must precede generation intents (#778, #670).
_INTENT_RULES: list[tuple[str, list[str]]] = [
    (
        "explain",
        [
            r"\bexplain\b",
            r"\bwhat does\b",
            r"\bhow does\b",
            r"\bhow do\b",
            r"\bhow (can|could|would|should) (i|we|you)\b",
            r"\bwhat (is|are)\s+(a|an)\b",
            r"\bwhat (is|are)\s+the\s+(purpose|difference|role|point|meaning|concept|idea)\b",
            r"\bwhat (is|are)\s+(ansible|salt|saltstack|jinja|yaml)\b",
            r"\bwhat (is|are)\s+(pillar|pillars|grain|grains|minion|minions|master)\b",
            r"\bwhat (is|are)\s+(state|states|playbook|playbooks|sls|module|modules)\b",
            r"\bwhat (is|are)\s+(role|roles|task|tasks|handler|handlers)\b",
            r"\bwhy (does|do|is|are|would|should)\b",
            r"\btell me (about|how|what|why)\b",
            r"\bcan you (explain|describe|tell me|show me how)\b",
            r"\bwhat is this\b",
            r"\bdescribe (this|the|a|an)\b",
            r"\bwhat('s| is) the (purpose|difference|role|point)\b",
        ],
    ),
    (
        "salt_state",
        [
            # Require an explicit generation verb — bare "salt state" or "sls" alone is
            # a conceptual question that the explain branch already handles (#670).
            r"\b(write|generate|create)\b.{0,50}\b(state|sls|salt)\b",
            r"\b(write|generate|create)\b.{0,20}\b\.sls\b",
            r"\bsalt\s+(file|module)\b",
        ],
    ),
    (
        "ansible_playbook",
        [
            # Require an explicit generation verb to avoid routing conceptual questions
            # like "how does a playbook work" or "what is ansible" to code-gen (#670).
            r"\b(write|generate|create)\b.{0,50}\b(playbook|ansible|yaml)\b",
            r"\b(playbook|ansible)\b.{0,40}\b(roles|tasks|handlers|yaml)\b",
            r"\b(roles|tasks|handlers)\b.{0,40}\b(playbook|ansible)\b",
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
