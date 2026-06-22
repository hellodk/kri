"""Unit tests for the LLM planner (#711).

The planner is exercised with a stubbed ``call_openai_compat`` so no network is
touched. We assert it (a) turns a JSON tool-call reply into a PlanDecision with
tool_calls, (b) treats plain prose as a final answer, (c) accumulates tokens,
and (d) drops calls naming an unknown tool.
"""

from __future__ import annotations

import fleet_platform.services.llm_caller as llm_caller
from fleet_platform.agent.planner import LLMPlanner
from fleet_platform.agent.tools import build_default_registry


def _planner(role: str = "operator") -> LLMPlanner:
    return LLMPlanner(
        registry=build_default_registry(),
        role=role,
        base_url="http://llm.local",
        model="test-model",
        max_tokens=512,
    )


async def test_plan_parses_json_tool_call(monkeypatch):
    async def fake_call(**kwargs):
        return '{"name": "list_nodes", "arguments": {"status": "degraded"}}', 11, 7

    monkeypatch.setattr(llm_caller, "call_openai_compat", fake_call)
    planner = _planner()
    decision = await planner.plan(prompt="what is degraded?", history=[], tool_results=[])
    assert decision.final is None
    assert len(decision.tool_calls) == 1
    assert decision.tool_calls[0].name == "list_nodes"
    assert decision.tool_calls[0].args == {"status": "degraded"}
    assert planner.input_tokens == 11 and planner.output_tokens == 7


async def test_plan_plain_text_is_final(monkeypatch):
    async def fake_call(**kwargs):
        return "mm7 is degraded because of high drift.", 5, 9

    monkeypatch.setattr(llm_caller, "call_openai_compat", fake_call)
    planner = _planner()
    decision = await planner.plan(prompt="why?", history=[], tool_results=[])
    assert decision.tool_calls == []
    assert decision.final == "mm7 is degraded because of high drift."


async def test_plan_drops_unknown_tool(monkeypatch):
    async def fake_call(**kwargs):
        return '{"name": "delete_everything", "arguments": {}}', 1, 1

    monkeypatch.setattr(llm_caller, "call_openai_compat", fake_call)
    planner = _planner()
    decision = await planner.plan(prompt="hi", history=[], tool_results=[])
    # Unknown tool → no tool calls; the raw text becomes the (best-effort) final.
    assert decision.tool_calls == []
    assert decision.final is not None


async def test_plan_accumulates_tokens_across_calls(monkeypatch):
    async def fake_call(**kwargs):
        return "done", 4, 6

    monkeypatch.setattr(llm_caller, "call_openai_compat", fake_call)
    planner = _planner()
    await planner.plan(prompt="a", history=[], tool_results=[])
    await planner.plan(prompt="b", history=[], tool_results=[])
    assert planner.input_tokens == 8 and planner.output_tokens == 12


def test_system_prompt_only_lists_role_tools():
    operator_prompt = _planner("operator")._system_prompt()
    viewer_prompt = _planner("viewer")._system_prompt()
    # get_recent_audit is admin-only — must not appear for operator/viewer.
    assert "get_recent_audit" not in operator_prompt
    assert "get_recent_audit" not in viewer_prompt
    # run_salt_cmd is operator+; present for operator, absent for viewer.
    assert "run_salt_cmd" in operator_prompt
    assert "run_salt_cmd" not in viewer_prompt
