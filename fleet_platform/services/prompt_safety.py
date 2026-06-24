"""Prompt-injection sanitization for fleet-controlled strings (#710).

Node fields (hostname, minion_id, group, ...) are operator/agent-controlled and
land verbatim in the LLM system prompt and, later, in tool results fed back into
the agent loop. A hostile or accidentally-crafted value must not be able to:

- open a Markdown/code fence (```), which can break out of a data block,
- smuggle model-control tokens (``<|python_tag|>``, ``<|im_start|>``, ...),
- present tool-call-shaped tokens (``tool_call``/``tool_use``/``function_call``)
  that a permissive parser might act on,
- hide payloads using control / format / bidi / private-use / surrogate Unicode
  (e.g. zero-width spaces or RLO/LRO bidi overrides).

`sanitize_untrusted` neutralizes all of the above. `is_suspicious` is the
detection counterpart used by the regression corpus and by ingest-time guards.
The contract the test suite pins: ``not is_suspicious(sanitize_untrusted(x))``
for every input ``x``.
"""

from __future__ import annotations

import re
import unicodedata

# Unicode general categories stripped wholesale: control, format (incl. bidi
# overrides + zero-width), private-use, surrogate. Common whitespace is kept and
# handled explicitly so table/line semantics are preserved.
_STRIP_CATEGORIES = frozenset({"Cc", "Cf", "Co", "Cs"})
_KEEP_CONTROL = frozenset({"\n", "\r", "\t"})

_FENCE_RE = re.compile(r"`{3,}")
_MODEL_TOKEN_RE = re.compile(r"<\|[^>]*?\|>")
_DANGLING_TOKEN_RE = re.compile(r"<\||\|>")
_TOOLCALL_RE = re.compile(r"(?i)\btool[_\s]*call\b|\btool[_\s]*use\b|\bfunction[_\s]*call\b")


def _has_stripped_unicode(text: str) -> bool:
    return any(ch not in _KEEP_CONTROL and unicodedata.category(ch) in _STRIP_CATEGORIES for ch in text)


def _strip_unicode(text: str) -> str:
    return "".join(ch for ch in text if ch in _KEEP_CONTROL or unicodedata.category(ch) not in _STRIP_CATEGORIES)


def is_suspicious(value: object) -> bool:
    """True if the value carries a prompt-injection / control marker."""
    text = str(value)
    if _has_stripped_unicode(text):
        return True
    if _FENCE_RE.search(text):
        return True
    if _MODEL_TOKEN_RE.search(text) or _DANGLING_TOKEN_RE.search(text):
        return True
    if _TOOLCALL_RE.search(text):
        return True
    return False


def sanitize_untrusted(value: object, *, cell: bool = False) -> str:
    """Defang a fleet-controlled string for safe inclusion in a prompt.

    Order matters: strip dangerous Unicode first (so zero-width-obfuscated
    tokens like ``t\u200boolcall`` collapse to a detectable form), then neutralize
    structural markers. With ``cell=True`` the result is also safe inside a
    Markdown table row (escapes ``|``, flattens newlines).
    """
    text = _strip_unicode(str(value))
    text = _FENCE_RE.sub("[code-fence]", text)
    text = _MODEL_TOKEN_RE.sub("[token]", text)
    text = _DANGLING_TOKEN_RE.sub("[token]", text)
    text = _TOOLCALL_RE.sub("[redacted]", text)
    if cell:
        text = text.replace("|", "\\|").replace("\n", " ").replace("\r", "")
    return text


# --- Output sanitization (#782) ---

_SCRIPT_RE = re.compile(r"<script[\s\S]*?</script\s*>", re.IGNORECASE)
_EVENT_ATTR_RE = re.compile(r"""\s+on\w+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]*)""", re.IGNORECASE)


def sanitize_llm_output(text: str) -> str:
    """Strip HTML script blocks and event-handler attrs from model output (#782).

    Applied at the API boundary before emitting the final SSE event so that
    injection-induced or LLM-hallucinated script payloads cannot execute in the
    operator's browser.  Safe content (plain prose, Markdown, code blocks) is
    preserved.
    """
    if not text:
        return text
    text = _SCRIPT_RE.sub("", text)
    text = _EVENT_ATTR_RE.sub("", text)
    return text


# --- Observation sanitization helpers (#770) ---


def sanitize_result_value(v: object) -> object:
    """Recursively sanitize string leaf values in a tool result payload (#770).

    Walks dicts and lists; applies sanitize_untrusted to every string found so
    hostile node data (code-fences, model-control tokens) cannot influence the
    model's next decision when the observation is fed back into the prompt.
    Non-string scalars and None pass through unchanged.
    """
    if isinstance(v, str):
        return sanitize_untrusted(v)
    if isinstance(v, dict):
        return {k: sanitize_result_value(val) for k, val in v.items()}
    if isinstance(v, list):
        return [sanitize_result_value(item) for item in v]
    return v


# --- Audit redaction helpers (#781) ---

# Keys (matched case-insensitively) whose values must always be redacted.
_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "secret",
        "token",
        "api_key",
        "apikey",
        "value",
        "content",
        "private_key",
        "privatekey",
        "credential",
        "passphrase",
        "auth",
    }
)


def is_sensitive_key(key: str) -> bool:
    """Return True if *key* (case-insensitive) matches any sensitive pattern."""
    return key.lower() in _SENSITIVE_KEYS


def redact_args(args: dict) -> dict:
    """Redact sensitive fields from tool-call argument dicts (#781).

    Two tiers:
    1. Key-name blocklist: keys matching _SENSITIVE_KEYS → '[REDACTED]'.
    2. Length cap: non-sensitive strings > 500 chars are truncated.
    """
    out: dict = {}
    for k, v in (args or {}).items():
        if is_sensitive_key(k):
            out[k] = "[REDACTED]"
        elif isinstance(v, str) and len(v) > 500:
            out[k] = v[:500] + "...[truncated]"
        else:
            out[k] = v
    return out
