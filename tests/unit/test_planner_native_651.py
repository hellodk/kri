"""Native + Anthropic tool-calling in the planner via ``tool_mode`` (#651).

The planner historically only used prompt-embedded JSON tool-calling and ignored
``LLMEndpoint.tool_mode``. These tests pin the three modes — ``native`` (OpenAI
``tools=[...]``), ``anthropic`` (``tool_use``), and ``json`` (content parsing) —
plus token accounting, all against a mocked caller so no network is touched.
"""

from __future__ import annotations

import json

import pytest

from fleet_platform.agent import planner as planner_mod
from fleet_platform.agent.planner import LLMPlanner
from fleet_platform.agent.registry import ToolRegistry, ToolSpec
from fleet_platform.services import llm_caller


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        ToolSpec(
            name="get_node_status",
            description="Return the status of a node.",
            params_schema={
                "type": "object",
                "properties": {"node": {"type": "string", "description": "node id"}},
                "required": ["node"],
            },
            required_role="viewer",
            side_effect="read",
        )
    )
    return reg


def _make_planner(tool_mode: str, **kw) -> LLMPlanner:
    return LLMPlanner(
        registry=_registry(),
        role="admin",
        base_url="http://endpoint.local",
        model="test-model",
        max_tokens=512,
        tool_mode=tool_mode,
        **kw,
    )


async def test_native_mode_parses_openai_tool_call(monkeypatch):
    """``tool_mode='native'`` reads a native OpenAI ``tool_calls`` entry."""
    captured: dict = {}

    async def fake_openai_tools(*, tools, system_prompt, **kwargs):
        captured["tools"] = tools
        captured["system_prompt"] = system_prompt
        message = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {"name": "get_node_status", "arguments": json.dumps({"node": "mm1"})},
                }
            ],
        }
        return message, 11, 7

    monkeypatch.setattr(llm_caller, "call_openai_compat_tools", fake_openai_tools)

    planner = _make_planner("native")
    decision = await planner.plan(prompt="status of mm1?", history=[], tool_results=[])

    assert decision.final is None
    assert [c.name for c in decision.tool_calls] == ["get_node_status"]
    assert decision.tool_calls[0].args == {"node": "mm1"}
    # Native tool schemas are sent out-of-band, not embedded in the prompt.
    assert captured["tools"] == planner.registry.to_openai_tools("admin")
    assert "get_node_status" not in captured["system_prompt"]


async def test_anthropic_mode_parses_tool_use(monkeypatch):
    """``tool_mode='anthropic'`` reads an Anthropic ``tool_use`` block."""
    captured: dict = {}

    async def fake_anthropic_tools(*, tools, **kwargs):
        captured["tools"] = tools
        message = {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"type": "tool_use", "id": "tu_1", "name": "get_node_status", "input": {"node": "mm2"}}],
        }
        return message, 13, 5

    monkeypatch.setattr(llm_caller, "call_anthropic_tools", fake_anthropic_tools)

    planner = _make_planner("anthropic")
    decision = await planner.plan(prompt="status of mm2?", history=[], tool_results=[])

    assert decision.final is None
    assert [c.name for c in decision.tool_calls] == ["get_node_status"]
    assert decision.tool_calls[0].args == {"node": "mm2"}
    assert captured["tools"] == planner.registry.to_anthropic_tools("admin")


async def test_json_mode_still_parses_from_content(monkeypatch):
    """Default ``json`` mode keeps the prompt-embedded content-parsing path."""
    captured: dict = {}

    async def fake_openai(*, system_prompt, **kwargs):
        captured["system_prompt"] = system_prompt
        content = json.dumps({"name": "get_node_status", "arguments": {"node": "mm3"}})
        return content, 9, 4

    monkeypatch.setattr(llm_caller, "call_openai_compat", fake_openai)

    planner = _make_planner("json")
    decision = await planner.plan(prompt="status of mm3?", history=[], tool_results=[])

    assert decision.final is None
    assert [c.name for c in decision.tool_calls] == ["get_node_status"]
    assert decision.tool_calls[0].args == {"node": "mm3"}
    # json mode DOES embed the tool catalogue in the prompt.
    assert "get_node_status" in captured["system_prompt"]


async def test_native_mode_falls_back_to_content_when_no_native_call(monkeypatch):
    """No native tool_calls -> content is parsed; plain prose becomes a final answer."""

    async def fake_openai_tools(**kwargs):
        message = {"role": "assistant", "content": "mm1 is healthy and online.", "tool_calls": []}
        return message, 3, 2

    monkeypatch.setattr(llm_caller, "call_openai_compat_tools", fake_openai_tools)

    planner = _make_planner("native")
    decision = await planner.plan(prompt="status?", history=[], tool_results=[])

    assert decision.tool_calls == []
    assert decision.final == "mm1 is healthy and online."


async def test_unknown_tool_name_is_filtered_to_final(monkeypatch):
    """A native call naming an unregistered tool is dropped, not dispatched."""

    async def fake_openai_tools(**kwargs):
        message = {
            "role": "assistant",
            "content": "done",
            "tool_calls": [{"id": "x", "function": {"name": "rm_minus_rf", "arguments": "{}"}}],
        }
        return message, 1, 1

    monkeypatch.setattr(llm_caller, "call_openai_compat_tools", fake_openai_tools)

    planner = _make_planner("native")
    decision = await planner.plan(prompt="?", history=[], tool_results=[])

    assert decision.tool_calls == []
    assert decision.final == "done"


async def test_token_accounting_accumulates_across_iterations(monkeypatch):
    """input/output token counts accumulate across successive plan() calls."""

    async def fake_openai_tools(**kwargs):
        message = {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c", "function": {"name": "get_node_status", "arguments": '{"node": "a"}'}}],
        }
        return message, 10, 20

    monkeypatch.setattr(llm_caller, "call_openai_compat_tools", fake_openai_tools)

    planner = _make_planner("native")
    await planner.plan(prompt="p", history=[], tool_results=[])
    await planner.plan(prompt="p", history=[], tool_results=[])

    assert planner.input_tokens == 20
    assert planner.output_tokens == 40


def test_planner_imported_module_exposes_native_preamble():
    """Guard: native modes must use a preamble that omits JSON-reply instructions."""
    assert "SINGLE JSON object" not in planner_mod._NATIVE_SYSTEM_PREAMBLE
    assert "SINGLE JSON object" in planner_mod._SYSTEM_PREAMBLE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
