"""Behavioral coverage for fleet_platform/agent/planner.py helpers (#799 / TST-2).

The planner feeds tool observations back into the model. Untrusted/fleet-controlled
strings in those observations must be sanitized so a hostile node value cannot
steer the next decision (#770), and the model's own output must be defanged before
it reaches the browser (#782). These tests assert that sanitization behavior and
the prompt-assembly logic, plus the Anthropic provider branch of ``plan``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import fleet_platform.services.llm_caller as llm_caller
from fleet_platform.agent.planner import (
    TOOL_RESULT_CAP,
    LLMPlanner,
    _sanitize_value,
    _summarize_result,
    sanitize_llm_output,
)
from fleet_platform.agent.tools import build_default_registry


@dataclass
class _Result:
    name: str
    ok: bool
    result: Any = None
    error: str | None = None
    status: str = "ok"


def _planner(role: str = "operator", provider: str = "openai") -> LLMPlanner:
    return LLMPlanner(
        registry=build_default_registry(),
        role=role,
        base_url="http://llm.local",
        model="test-model",
        max_tokens=256,
        provider=provider,
        api_key="k",
    )


def test_summarize_ok_result_sanitizes_hostile_strings():
    line = _summarize_result(_Result(name="get_node", ok=True, result={"hostname": "evil```code"}))
    assert line.startswith("[get_node] OK:")
    # A code-fence in fleet data is neutralized, not passed through verbatim.
    assert "```" not in line
    assert "[code-fence]" in line


def test_summarize_error_result_sanitizes_and_marks_error():
    line = _summarize_result(_Result(name="ping_node", ok=False, error="boom<|im_start|>"))
    assert line.startswith("[ping_node] ERROR:")
    assert "<|im_start|>" not in line
    assert "[token]" in line


def test_summarize_error_falls_back_to_status_when_no_error():
    line = _summarize_result(_Result(name="t", ok=False, error=None, status="denied"))
    assert line == "[t] ERROR: denied"


def test_summarize_truncates_oversized_payload():
    big = "a" * (TOOL_RESULT_CAP + 500)
    line = _summarize_result(_Result(name="rag_search", ok=True, result=big))
    assert "...[truncated]" in line
    assert len(line) < len(big)


def test_sanitize_value_recurses_into_containers():
    cleaned = _sanitize_value({"a": ["x```y", {"b": "<|tool|>"}], "n": 3})
    assert "```" not in str(cleaned)
    assert "<|tool|>" not in str(cleaned)
    # Non-string scalars pass through unchanged.
    assert cleaned["n"] == 3


def test_sanitize_llm_output_strips_script_blocks():
    out = sanitize_llm_output("hello <script>steal()</script> world")
    assert "<script>" not in out
    assert "hello" in out and "world" in out


def test_user_prompt_without_results_is_passthrough():
    assert _planner()._user_prompt("plain question", []) == "plain question"


def test_user_prompt_with_results_includes_observations():
    p = _planner()._user_prompt("why degraded?", [_Result(name="list_nodes", ok=True, result={"count": 2})])
    assert "Original question: why degraded?" in p
    assert "[list_nodes] OK:" in p
    assert "next tool call" in p


async def test_plan_uses_anthropic_provider_branch(monkeypatch):
    seen: dict = {}

    async def fake_anthropic(**kwargs):
        seen.update(kwargs)
        return '{"name": "list_nodes", "arguments": {"status": "degraded"}}', 3, 4

    monkeypatch.setattr(llm_caller, "call_anthropic", fake_anthropic)
    planner = _planner(provider="anthropic")
    decision = await planner.plan(prompt="q", history=[], tool_results=[])

    assert decision.tool_calls and decision.tool_calls[0].name == "list_nodes"
    assert planner.input_tokens == 3 and planner.output_tokens == 4
    # The anthropic caller receives the assembled system prompt.
    assert "Available Tools" in seen["system_prompt"]
