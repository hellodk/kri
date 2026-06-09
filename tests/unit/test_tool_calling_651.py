# tests/unit/test_tool_calling_651.py
"""Behavioral unit tests for fleet_platform.services.tool_calling (issue #651).

All tests are deterministic and require no network, DB, or LLM.
"""

from fleet_platform.services.tool_calling import (
    ToolCallAccumulator,
    extract_tool_calls,
    normalize_tool_call,
    parse_tool_calls_from_content,
)

# ---------------------------------------------------------------------------
# Fixtures / shared data
# ---------------------------------------------------------------------------

# The exact exo capture from the issue spec.
EXO_CONTENT = (
    '<|python_tag|>{"name": "get_node_status", "parameters": {"node": "mm1"}}'
    "<|eom_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
    "This JSON represents a function call..."
)

THINK_THEN_CALL = (
    "<think>I need to look up the node status first.</think>"
    '<|python_tag|>{"name": "get_node_status", "parameters": {"node": "mm1"}}<|eom_id|>'
)

PLAIN_TEXT = "The current date is 2026-06-09 and everything is healthy."

PLAIN_TEXT_WITH_STRAY_BRACES = "Results: {count: 3, ok: true} — no issues."


# ---------------------------------------------------------------------------
# parse_tool_calls_from_content
# ---------------------------------------------------------------------------


class TestParseToolCallsFromContent:
    def test_exo_exact_capture(self) -> None:
        """The real exo output must produce exactly one ToolCall with the right args."""
        calls = parse_tool_calls_from_content(EXO_CONTENT)
        assert len(calls) == 1
        tc = calls[0]
        assert tc.name == "get_node_status"
        assert tc.arguments == {"node": "mm1"}

    def test_trailing_prose_ignored(self) -> None:
        """Text after the JSON block must not cause extra ToolCalls or errors."""
        calls = parse_tool_calls_from_content(EXO_CONTENT)
        # Still exactly one call despite the prose suffix.
        assert len(calls) == 1

    def test_markers_stripped(self) -> None:
        """All Llama special tokens must be stripped before parsing."""
        content = '<|python_tag|>{"name": "ping", "parameters": {}}<|eot_id|>'
        calls = parse_tool_calls_from_content(content)
        assert len(calls) == 1
        assert calls[0].name == "ping"

    def test_think_block_then_tool_call(self) -> None:
        """<think>...</think> must be removed; the embedded tool call must survive."""
        calls = parse_tool_calls_from_content(THINK_THEN_CALL)
        assert len(calls) == 1
        assert calls[0].name == "get_node_status"
        assert calls[0].arguments == {"node": "mm1"}

    def test_think_block_multiline(self) -> None:
        """Multi-line think blocks must be stripped (DOTALL)."""
        content = (
            "<think>\nLine one.\nLine two.\n</think>"
            '<|python_tag|>{"name": "run_check", "parameters": {"host": "x"}}<|eom_id|>'
        )
        calls = parse_tool_calls_from_content(content)
        assert len(calls) == 1
        assert calls[0].name == "run_check"

    def test_plain_answer_returns_empty(self) -> None:
        """A plain-text answer with no JSON must return an empty list."""
        assert parse_tool_calls_from_content(PLAIN_TEXT) == []

    def test_json_without_name_key_ignored(self) -> None:
        """A JSON object that has no name/function/tool_use key must be ignored."""
        # e.g. {"count": 3, "ok": true} — not a tool call
        assert parse_tool_calls_from_content(PLAIN_TEXT_WITH_STRAY_BRACES) == []

    def test_empty_string_returns_empty(self) -> None:
        assert parse_tool_calls_from_content("") == []

    def test_openai_function_form_in_content(self) -> None:
        """OpenAI-style function object embedded in content is also extracted."""
        content = '{"function": {"name": "list_nodes", "arguments": "{}"}}'
        calls = parse_tool_calls_from_content(content)
        assert len(calls) == 1
        assert calls[0].name == "list_nodes"

    def test_anthropic_tool_use_form_in_content(self) -> None:
        """Anthropic tool_use embedded in content is also extracted."""
        content = '{"type": "tool_use", "name": "reboot_node", "input": {"node": "cylon"}}'
        calls = parse_tool_calls_from_content(content)
        assert len(calls) == 1
        assert calls[0].name == "reboot_node"
        assert calls[0].arguments == {"node": "cylon"}


# ---------------------------------------------------------------------------
# normalize_tool_call
# ---------------------------------------------------------------------------


class TestNormalizeToolCall:
    def test_openai_stringified_arguments(self) -> None:
        """OpenAI native: arguments is a JSON-string — must be parsed to dict."""
        raw = {
            "id": "call_abc",
            "function": {
                "name": "get_node_status",
                "arguments": '{"node": "mm1"}',
            },
        }
        tc = normalize_tool_call(raw)
        assert tc is not None
        assert tc.name == "get_node_status"
        assert tc.arguments == {"node": "mm1"}
        assert tc.id == "call_abc"

    def test_openai_dict_arguments(self) -> None:
        """If arguments is already a dict (some local servers), use as-is."""
        raw = {
            "id": "call_xyz",
            "function": {
                "name": "list_nodes",
                "arguments": {"filter": "active"},
            },
        }
        tc = normalize_tool_call(raw)
        assert tc is not None
        assert tc.arguments == {"filter": "active"}

    def test_openai_empty_arguments_string(self) -> None:
        """Empty arguments string → empty dict, not an error."""
        raw = {"id": "c1", "function": {"name": "ping", "arguments": ""}}
        tc = normalize_tool_call(raw)
        assert tc is not None
        assert tc.arguments == {}

    def test_openai_invalid_arguments_json(self) -> None:
        """Malformed JSON in arguments → empty dict fallback."""
        raw = {"id": "c2", "function": {"name": "ping", "arguments": "not-json{"}}
        tc = normalize_tool_call(raw)
        assert tc is not None
        assert tc.arguments == {}

    def test_llama_parameters_form(self) -> None:
        """Llama / exo content form: name + parameters."""
        raw = {"name": "get_node_status", "parameters": {"node": "mm1"}}
        tc = normalize_tool_call(raw)
        assert tc is not None
        assert tc.name == "get_node_status"
        assert tc.arguments == {"node": "mm1"}

    def test_anthropic_input_form(self) -> None:
        """Anthropic tool_use: type + name + input."""
        raw = {"type": "tool_use", "name": "reboot_node", "input": {"node": "cylon"}}
        tc = normalize_tool_call(raw)
        assert tc is not None
        assert tc.name == "reboot_node"
        assert tc.arguments == {"node": "cylon"}

    def test_generic_arguments_as_dict(self) -> None:
        """Generic form: top-level name + arguments dict."""
        raw = {"name": "list_nodes", "arguments": {"fleet": "all"}}
        tc = normalize_tool_call(raw)
        assert tc is not None
        assert tc.name == "list_nodes"
        assert tc.arguments == {"fleet": "all"}

    def test_missing_name_returns_none(self) -> None:
        """If there is no usable name anywhere → return None."""
        assert normalize_tool_call({}) is None
        assert normalize_tool_call({"arguments": {"x": 1}}) is None

    def test_empty_name_returns_none(self) -> None:
        """Explicitly empty name string → None."""
        raw = {"name": "", "parameters": {"x": 1}}
        assert normalize_tool_call(raw) is None

    def test_no_id_is_fine(self) -> None:
        """Missing id → id=None, no error."""
        raw = {"name": "ping", "parameters": {}}
        tc = normalize_tool_call(raw)
        assert tc is not None
        assert tc.id is None


# ---------------------------------------------------------------------------
# ToolCallAccumulator
# ---------------------------------------------------------------------------


class TestToolCallAccumulator:
    def _make_delta(
        self,
        index: int,
        call_id: str | None = None,
        name: str | None = None,
        arguments: str = "",
    ) -> dict:
        fn: dict = {}
        if name is not None:
            fn["name"] = name
        if arguments:
            fn["arguments"] = arguments
        entry: dict = {"index": index, "function": fn}
        if call_id is not None:
            entry["id"] = call_id
        return {"tool_calls": [entry]}

    def test_single_tool_call_three_fragments(self) -> None:
        """Name in first chunk, arguments split across all three → one ToolCall."""
        acc = ToolCallAccumulator()
        acc.add_delta(self._make_delta(0, call_id="call_1", name="get_node_status", arguments=""))
        acc.add_delta(self._make_delta(0, arguments='{"node":'))
        acc.add_delta(self._make_delta(0, arguments=' "mm1"}'))
        calls = acc.finalize()
        assert len(calls) == 1
        tc = calls[0]
        assert tc.name == "get_node_status"
        assert tc.arguments == {"node": "mm1"}
        assert tc.id == "call_1"

    def test_two_concurrent_indices_ordered(self) -> None:
        """Two concurrent tool calls at index 0 and 1 → two ToolCalls in index order."""
        acc = ToolCallAccumulator()
        # First tool call at index 0
        acc.add_delta(self._make_delta(0, call_id="call_a", name="get_node_status", arguments=""))
        acc.add_delta(self._make_delta(0, arguments='{"node": "mm1"}'))
        # Second tool call at index 1
        acc.add_delta(self._make_delta(1, call_id="call_b", name="list_nodes", arguments=""))
        acc.add_delta(self._make_delta(1, arguments='{"fleet": "all"}'))
        calls = acc.finalize()
        assert len(calls) == 2
        assert calls[0].name == "get_node_status"
        assert calls[0].arguments == {"node": "mm1"}
        assert calls[1].name == "list_nodes"
        assert calls[1].arguments == {"fleet": "all"}

    def test_empty_accumulator_returns_empty(self) -> None:
        acc = ToolCallAccumulator()
        assert acc.finalize() == []

    def test_delta_with_no_tool_calls_key_ignored(self) -> None:
        """Delta without tool_calls key (e.g. content delta) must be silently ignored."""
        acc = ToolCallAccumulator()
        acc.add_delta({"content": "Hello"})
        assert acc.finalize() == []

    def test_invalid_arguments_json_falls_back_to_empty(self) -> None:
        """If concatenated fragments can't be parsed → arguments={}."""
        acc = ToolCallAccumulator()
        acc.add_delta(self._make_delta(0, call_id="c", name="ping", arguments=""))
        acc.add_delta(self._make_delta(0, arguments="not-valid-json"))
        calls = acc.finalize()
        assert len(calls) == 1
        assert calls[0].arguments == {}

    def test_id_set_in_later_chunk(self) -> None:
        """id may arrive in a later chunk; it must still be captured."""
        acc = ToolCallAccumulator()
        acc.add_delta(self._make_delta(0, name="ping", arguments=""))
        # id arrives in a second chunk alongside more args
        delta2: dict = {"tool_calls": [{"index": 0, "id": "late_id", "function": {"arguments": "{}"}}]}
        acc.add_delta(delta2)
        calls = acc.finalize()
        assert calls[0].id == "late_id"


# ---------------------------------------------------------------------------
# extract_tool_calls
# ---------------------------------------------------------------------------


class TestExtractToolCalls:
    def test_native_tool_calls_used_when_present(self) -> None:
        """message with non-empty tool_calls list → use them, not content."""
        message = {
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {
                        "name": "get_node_status",
                        "arguments": '{"node": "mm1"}',
                    },
                }
            ],
            "content": "this prose must be ignored",
        }
        calls = extract_tool_calls(message)
        assert len(calls) == 1
        assert calls[0].name == "get_node_status"
        assert calls[0].arguments == {"node": "mm1"}

    def test_null_tool_calls_falls_back_to_content(self) -> None:
        """message with tool_calls=None → parse content-embedded call."""
        message = {
            "tool_calls": None,
            "content": (
                '<|python_tag|>{"name": "get_node_status", "parameters": {"node": "mm1"}}'
                "<|eom_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
                "This JSON represents a function call..."
            ),
        }
        calls = extract_tool_calls(message)
        assert len(calls) == 1
        assert calls[0].name == "get_node_status"
        assert calls[0].arguments == {"node": "mm1"}

    def test_missing_tool_calls_key_falls_back_to_content(self) -> None:
        """message without tool_calls key → fall back to content parse."""
        message = {
            "content": '<|python_tag|>{"name": "ping", "parameters": {}}<|eom_id|>',
        }
        calls = extract_tool_calls(message)
        assert len(calls) == 1
        assert calls[0].name == "ping"

    def test_empty_tool_calls_list_falls_back_to_content(self) -> None:
        """tool_calls=[] (empty list) → treat as absent → fall back to content."""
        message = {
            "tool_calls": [],
            "content": '<|python_tag|>{"name": "list_nodes", "parameters": {}}<|eom_id|>',
        }
        calls = extract_tool_calls(message)
        assert len(calls) == 1
        assert calls[0].name == "list_nodes"

    def test_plain_text_message_returns_empty(self) -> None:
        """Plain text answer with no tool call in either field → []."""
        message = {"tool_calls": None, "content": "Everything looks fine."}
        assert extract_tool_calls(message) == []

    def test_multiple_native_tool_calls(self) -> None:
        """Multiple entries in tool_calls list → all normalized."""
        message = {
            "tool_calls": [
                {"id": "c1", "function": {"name": "get_node_status", "arguments": '{"node":"mm1"}'}},
                {"id": "c2", "function": {"name": "list_nodes", "arguments": "{}"}},
            ]
        }
        calls = extract_tool_calls(message)
        assert len(calls) == 2
        assert calls[0].name == "get_node_status"
        assert calls[1].name == "list_nodes"
