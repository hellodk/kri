"""LLM-backed planner for the agent loop (#711).

The :class:`AgentLoop` depends only on a ``Planner`` protocol; this module
provides the production implementation. It uses **prompt-embedded** tool calling
(``tool_mode="json"``): the available tools are rendered into the system prompt
and the model replies either with a JSON tool-call object or a plain-text final
answer. This works with the existing buffered LLM callers (``call_openai_compat``
/ ``call_anthropic``) without any change to the streaming infrastructure, and the
backend-agnostic :func:`parse_tool_calls_from_content` extracts the call.

Token usage accumulates across iterations so the route can persist it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fleet_platform.agent.loop import PlanDecision, ToolCall
from fleet_platform.agent.registry import ToolRegistry
from fleet_platform.services.tool_calling import parse_tool_calls_from_content

_SYSTEM_PREAMBLE = (
    "You are kri's fleet operations agent. You answer the operator's question by "
    "calling read-only tools, observing their results, and reasoning step by step.\n\n"
    "RULES:\n"
    "- To call a tool, reply with a SINGLE JSON object and nothing else: "
    '{"name": "<tool_name>", "arguments": {<args>}}\n'
    "- Call one tool at a time. Wait for its result before deciding the next step.\n"
    "- Only use tools from the list below; never invent tool names or arguments.\n"
    "- When you have enough information, reply with a plain-text final answer "
    "(NO JSON). Be concise and cite the node/minion ids you inspected.\n"
    "- If a tool errors or a question cannot be answered with the available tools, "
    "say so plainly in a final answer.\n"
)


def _summarize_result(result: Any) -> str:
    """Compact a ToolResult into a single observation line for the next prompt."""
    name = getattr(result, "name", "?")
    ok = getattr(result, "ok", False)
    if not ok:
        return f"[{name}] ERROR: {getattr(result, 'error', None) or getattr(result, 'status', 'error')}"
    import json as _json

    try:
        payload = _json.dumps(getattr(result, "result", None), default=str)
    except (TypeError, ValueError):
        payload = str(getattr(result, "result", None))
    if len(payload) > 4000:
        payload = payload[:4000] + " ...[truncated]"
    return f"[{name}] OK: {payload}"


@dataclass
class LLMPlanner:
    """Planner that asks an LLM endpoint which tool to call next (json tool_mode)."""

    registry: ToolRegistry
    role: str
    base_url: str
    model: str
    max_tokens: int
    api_key: str | None = None
    provider: str = "openai"
    model_context_length: int | None = None
    model_capabilities: list[str] = field(default_factory=list)

    input_tokens: int = 0
    output_tokens: int = 0

    def _system_prompt(self) -> str:
        return _SYSTEM_PREAMBLE + "\n" + self.registry.to_prompt_section(self.role)

    def _user_prompt(self, prompt: str, tool_results: list[Any]) -> str:
        if not tool_results:
            return prompt
        observations = "\n".join(_summarize_result(r) for r in tool_results)
        return (
            f"Original question: {prompt}\n\n"
            f"Tool observations so far:\n{observations}\n\n"
            "Decide the next tool call, or give your final answer."
        )

    async def plan(self, *, prompt: str, history: list[dict], tool_results: list[Any]) -> PlanDecision:
        from fleet_platform.services.llm_caller import call_anthropic, call_openai_compat

        system_prompt = self._system_prompt()
        user_prompt = self._user_prompt(prompt, tool_results)

        if self.provider == "anthropic":
            content, in_tok, out_tok = await call_anthropic(
                api_key=self.api_key or "",
                model=self.model,
                max_tokens=self.max_tokens,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                history=None,
            )
        else:
            content, in_tok, out_tok = await call_openai_compat(
                base_url=self.base_url,
                api_key=self.api_key,
                model=self.model,
                max_tokens=self.max_tokens,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                history=None,
                model_context_length=self.model_context_length,
                model_capabilities=self.model_capabilities,
            )

        self.input_tokens += int(in_tok or 0)
        self.output_tokens += int(out_tok or 0)

        calls = parse_tool_calls_from_content(content or "")
        # Keep only calls naming a tool the role may actually use; the executor
        # re-checks, but filtering here avoids burning a tool-call slot on noise.
        valid = [c for c in calls if self.registry.get(c.name) is not None]
        if valid:
            return PlanDecision(tool_calls=[ToolCall(name=c.name, args=c.arguments) for c in valid[:1]])

        return PlanDecision(final=(content or "").strip())
