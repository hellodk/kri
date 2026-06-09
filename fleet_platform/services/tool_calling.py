# fleet_platform/services/tool_calling.py
"""Backend-agnostic tool-call normalizer, content parser, and streaming accumulator.

No network I/O — pure logic.  Supports:
- OpenAI native tool_calls (stringified or dict arguments)
- Llama / exo "parameters" form
- Anthropic "tool_use / input" form
- Inline content-embedded calls (exo / mlx emit these when tool_calls is null)
- SSE streaming fragment accumulation (OpenAI native streaming)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass
class ToolCall:
    name: str
    arguments: dict  # always a parsed dict, never a raw string
    id: str | None = None


# ---------------------------------------------------------------------------
# Marker / think-block stripping
# ---------------------------------------------------------------------------

# Llama-family special tokens that models inject into content.
_MARKERS: tuple[str, ...] = (
    "<|python_tag|>",
    "<|eom_id|>",
    "<|eot_id|>",
    "<|start_header_id|>",
    "<|end_header_id|>",
)

# Matches <think>...</think> with arbitrary nesting / newlines.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_markers(text: str) -> str:
    """Remove model-specific special tokens and <think> blocks."""
    text = _THINK_RE.sub("", text)
    for marker in _MARKERS:
        text = text.replace(marker, "")
    return text


# ---------------------------------------------------------------------------
# Brace-matching JSON extractor
# ---------------------------------------------------------------------------


def _extract_json_objects(text: str) -> list[str]:
    """Scan *text* for balanced `{...}` objects and return each as a raw string.

    Uses a simple character-by-character depth counter so it handles nested
    objects correctly and ignores trailing prose / non-JSON text.
    Strings containing `{` or `}` are handled by tracking quote state.
    """
    candidates: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        # Found the start of a potential object — brace-match to find the end.
        depth = 0
        in_string = False
        escape_next = False
        j = i
        while j < n:
            ch = text[j]
            if escape_next:
                escape_next = False
                j += 1
                continue
            if ch == "\\" and in_string:
                escape_next = True
                j += 1
                continue
            if ch == '"':
                in_string = not in_string
            elif not in_string:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidates.append(text[i : j + 1])
                        i = j + 1
                        break
            j += 1
        else:
            # Reached end without balancing — skip this `{`.
            i += 1
    return candidates


# ---------------------------------------------------------------------------
# 1. normalize_tool_call
# ---------------------------------------------------------------------------


def normalize_tool_call(raw: dict) -> ToolCall | None:
    """Normalize a raw tool-call dict (from any backend) to a ``ToolCall``.

    Accepted shapes:

    * **OpenAI native** – ``{"id": "...", "function": {"name": "X", "arguments": "<json>"}}``.
      ``arguments`` may be a JSON *string* (OpenAI streaming) or already a dict.
    * **Llama / exo content form** – ``{"name": "X", "parameters": {...}}``.
    * **Anthropic** – ``{"type": "tool_use", "name": "X", "input": {...}}``.
    * **Generic dict** – top-level ``"arguments"`` key as dict.

    Returns ``None`` when no usable name is found.
    """
    call_id: str | None = raw.get("id")

    # --- OpenAI native: has a "function" sub-dict ---
    if "function" in raw:
        fn = raw["function"]
        name = fn.get("name") or ""
        if not name:
            return None
        args_raw = fn.get("arguments", {})
        arguments = _parse_arguments(args_raw)
        return ToolCall(name=name, arguments=arguments, id=call_id)

    # --- Anthropic tool_use: has "type": "tool_use" and "input" ---
    if raw.get("type") == "tool_use":
        name = raw.get("name") or ""
        if not name:
            return None
        arguments = _parse_arguments(raw.get("input", {}))
        return ToolCall(name=name, arguments=arguments, id=call_id)

    # --- Llama / exo content form: top-level "name" + "parameters" ---
    if "parameters" in raw:
        name = raw.get("name") or ""
        if not name:
            return None
        arguments = _parse_arguments(raw["parameters"])
        return ToolCall(name=name, arguments=arguments, id=call_id)

    # --- Generic: top-level "name" + "arguments" ---
    if "name" in raw:
        name = raw.get("name") or ""
        if not name:
            return None
        arguments = _parse_arguments(raw.get("arguments", {}))
        return ToolCall(name=name, arguments=arguments, id=call_id)

    return None


def _parse_arguments(args_raw: Any) -> dict:
    """Return a parsed dict from *args_raw*, which may be a dict, JSON string, or garbage."""
    if isinstance(args_raw, dict):
        return args_raw
    if isinstance(args_raw, str):
        stripped = args_raw.strip()
        if not stripped:
            return {}
        try:
            parsed = json.loads(stripped)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, ValueError):
            return {}
    return {}


# ---------------------------------------------------------------------------
# 2. parse_tool_calls_from_content
# ---------------------------------------------------------------------------


def parse_tool_calls_from_content(content: str) -> list[ToolCall]:
    """Extract tool calls embedded inline in *content* (the critical exo path).

    exo / mlx models emit calls inside model-marker tokens in *content* while
    ``tool_calls`` in the API response remains ``null``.  Example real capture::

        <|python_tag|>{"name": "get_node_status", "parameters": {"node": "mm1"}}<|eom_id|>
        <|start_header_id|>assistant<|end_header_id|>\\n\\nThis JSON represents...

    Algorithm:
    1. Strip ``<think>...</think>`` blocks and Llama special-token markers.
    2. Brace-scan the remaining text for balanced ``{...}`` candidates.
    3. ``json.loads`` each candidate; keep only those that look like a tool call
       (have a ``"name"``, ``"function"``, or ``"type": "tool_use"`` key).
    4. Normalize each keeper via ``normalize_tool_call``.

    Returns an empty list when no tool call is present — a plain-text answer.
    """
    cleaned = _strip_markers(content)
    candidates = _extract_json_objects(cleaned)
    tool_calls: list[ToolCall] = []
    for candidate_str in candidates:
        try:
            obj = json.loads(candidate_str)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        # Filter: must look like a tool call.
        has_tool_call_shape = "name" in obj or "function" in obj or obj.get("type") == "tool_use"
        if not has_tool_call_shape:
            continue
        tc = normalize_tool_call(obj)
        if tc is not None:
            tool_calls.append(tc)
    return tool_calls


# ---------------------------------------------------------------------------
# 3. ToolCallAccumulator (native OpenAI streaming)
# ---------------------------------------------------------------------------


@dataclass
class _AccumulatedEntry:
    call_id: str | None = None
    name: str = ""
    arguments_fragments: list[str] = field(default_factory=list)


class ToolCallAccumulator:
    """Accumulate fragmented ``tool_calls`` deltas from an OpenAI-style SSE stream.

    OpenAI sends::

        # first chunk: id + name, arguments starts empty
        {"index": 0, "id": "call_abc", "function": {"name": "get_node_status", "arguments": ""}}
        # subsequent chunks: only arguments fragment
        {"index": 0, "function": {"arguments": "{\"node\":"}}
        {"index": 0, "function": {"arguments": " \"mm1\"}"}}

    Usage::

        acc = ToolCallAccumulator()
        for chunk in stream:
            delta = chunk["choices"][0]["delta"]
            acc.add_delta(delta)
        tool_calls = acc.finalize()
    """

    def __init__(self) -> None:
        self._entries: dict[int, _AccumulatedEntry] = {}

    def add_delta(self, delta: dict) -> None:
        """Process one SSE ``delta`` dict (the value of ``choices[0].delta``)."""
        raw_tc_list = delta.get("tool_calls")
        if not raw_tc_list:
            return
        for entry_dict in raw_tc_list:
            index: int = entry_dict.get("index", 0)
            if index not in self._entries:
                self._entries[index] = _AccumulatedEntry()
            entry = self._entries[index]

            if entry_dict.get("id"):
                entry.call_id = entry_dict["id"]

            fn = entry_dict.get("function", {})
            if fn.get("name"):
                entry.name = fn["name"]
            args_fragment: str = fn.get("arguments", "")
            if args_fragment:
                entry.arguments_fragments.append(args_fragment)

    def finalize(self) -> list[ToolCall]:
        """Return the accumulated ``ToolCall`` list, ordered by index."""
        result: list[ToolCall] = []
        for index in sorted(self._entries):
            entry = self._entries[index]
            if not entry.name:
                continue
            raw_args = "".join(entry.arguments_fragments)
            arguments = _parse_arguments(raw_args)
            result.append(ToolCall(name=entry.name, arguments=arguments, id=entry.call_id))
        return result


# ---------------------------------------------------------------------------
# 4. extract_tool_calls — single backend-agnostic entry point
# ---------------------------------------------------------------------------


def extract_tool_calls(message: dict) -> list[ToolCall]:
    """Extract tool calls from a non-streaming ``choices[0].message`` dict.

    Strategy:
    - If ``message["tool_calls"]`` is a non-empty list → normalize each entry.
    - Otherwise → fall back to ``parse_tool_calls_from_content`` on the content.

    This makes the caller fully backend-agnostic: the same code handles
    OpenAI native, Anthropic, Llama-family, and exo/mlx inline content.
    """
    native = message.get("tool_calls")
    if native and isinstance(native, list):
        result: list[ToolCall] = []
        for raw in native:
            tc = normalize_tool_call(raw)
            if tc is not None:
                result.append(tc)
        return result

    # Fall back to content-embedded parsing (exo / mlx path).
    content = message.get("content") or ""
    return parse_tool_calls_from_content(content)
