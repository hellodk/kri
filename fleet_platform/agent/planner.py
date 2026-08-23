"""LLM-backed planner for the agent loop (#711, #651).

The :class:`AgentLoop` depends only on a ``Planner`` protocol; this module
provides the production implementation. It honours ``LLMEndpoint.tool_mode``:

* ``json`` (default) — **prompt-embedded** tool calling: the available tools are
  rendered into the system prompt and the model replies with either a JSON
  tool-call object or a plain-text final answer. Uses the buffered callers
  (``call_openai_compat`` / ``call_anthropic``) and extracts calls from content.
* ``native`` — provider-native OpenAI ``tools=[...]`` calling via
  ``call_openai_compat_tools``; native ``tool_calls`` are read off the returned
  message (with a content-parse fallback).
* ``anthropic`` — Anthropic ``tools=[...]`` (``tool_use``) calling via
  ``call_anthropic_tools``.

In every mode :func:`extract_tool_calls` falls back to content parsing when the
endpoint returns no native call, so a weak/quirky model still works.

Token usage accumulates across iterations so the route can persist it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fleet_platform.agent.loop import PlanDecision, ToolCall
from fleet_platform.agent.registry import ToolRegistry
from fleet_platform.services.tool_calling import extract_tool_calls, parse_tool_calls_from_content

# Hard cap on a single tool result fed back into the planner prompt (#715). Keeps
# a hostile/huge tool result from blowing the context window or smuggling payload.
TOOL_RESULT_CAP = 4096

# Observation window (#1048): the two newest tool results are kept verbatim so
# the planner can reason over fresh data; everything older is collapsed into a
# bounded one-line-per-call digest. This caps total user-prompt growth no
# matter how many iterations a run takes.
_VERBATIM_TAIL = 2
_DIGEST_MAX_LINES = 12
_DIGEST_LINE_CAP = 80

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

# Native / anthropic modes pass tool schemas out-of-band (``tools=[...]``), so the
# system prompt must NOT instruct a JSON reply shape or list the tools inline —
# doing so confuses provider-native tool-calling. Only the behavioural rules stay.
_NATIVE_SYSTEM_PREAMBLE = (
    "You are kri's fleet operations agent. You answer the operator's question by "
    "calling read-only tools, observing their results, and reasoning step by step.\n\n"
    "RULES:\n"
    "- Use the provided tools to gather information. Call one tool at a time and "
    "wait for its result before deciding the next step.\n"
    "- Only use the tools provided; never invent tool names or arguments.\n"
    "- When you have enough information, reply with a plain-text final answer. "
    "Be concise and cite the node/minion ids you inspected.\n"
    "- If a tool errors or a question cannot be answered with the available tools, "
    "say so plainly in a final answer.\n"
)


def _sanitize_value(v: Any) -> Any:
    """Recursively sanitize string leaves in a tool result value (#770)."""
    from fleet_platform.services.prompt_safety import sanitize_result_value

    return sanitize_result_value(v)


def _summarize_result(result: Any) -> str:
    """Compact a ToolResult into a single sanitized observation line (#770).

    String values in the result payload are sanitized before serialization so
    hostile node data (code-fences, model-control tokens, tool-call shapes)
    cannot influence the model's next decision.
    """
    import json as _json

    name = getattr(result, "name", "?")
    ok = getattr(result, "ok", False)
    if not ok:
        from fleet_platform.services.prompt_safety import sanitize_untrusted

        raw_err = getattr(result, "error", None) or getattr(result, "status", "error")
        safe_err = sanitize_untrusted(str(raw_err)) if raw_err is not None else "error"
        return f"[{name}] ERROR: {safe_err}"

    sanitized = _sanitize_value(getattr(result, "result", None))
    try:
        payload = _json.dumps(sanitized, default=str)
    except (TypeError, ValueError):
        payload = str(sanitized)
    if len(payload) > TOOL_RESULT_CAP:
        payload = payload[:TOOL_RESULT_CAP] + " ...[truncated]"
    return f"[{name}] OK: {payload}"


def sanitize_llm_output(text: str) -> str:
    """Escape/strip HTML that could execute in the browser if rendered naively (#782)."""
    from fleet_platform.services.prompt_safety import sanitize_llm_output as _impl

    return _impl(text)


def _digest_line(result: Any) -> str:
    """One bounded line per collapsed observation: tool name + ok/error (#1048)."""
    name = getattr(result, "name", "?")
    ok = getattr(result, "ok", False)
    if not ok:
        from fleet_platform.services.prompt_safety import sanitize_untrusted

        raw_err = getattr(result, "error", None) or getattr(result, "status", "error")
        safe_err = sanitize_untrusted(str(raw_err)) if raw_err is not None else "error"
        line = f"[{name}] ERROR: {safe_err}"
    else:
        line = f"[{name}] OK"
    return line[:_DIGEST_LINE_CAP]


def _digest(older: list[Any]) -> str:
    """Collapse all but the newest observations into ≤12 one-liner lines (#1048).

    When more than ``_DIGEST_MAX_LINES`` older calls exist the most recent are
    kept and a single omission marker notes how many were dropped, so prompt
    growth stays bounded across arbitrarily long runs.
    """
    lines = [_digest_line(r) for r in older]
    omitted = 0
    if len(lines) > _DIGEST_MAX_LINES:
        omitted = len(lines) - _DIGEST_MAX_LINES
        lines = lines[-_DIGEST_MAX_LINES:]
    if omitted:
        lines.insert(0, f"(+{omitted} earlier tool calls omitted)")
    return "\n".join(lines)


@dataclass
class LLMPlanner:
    """Planner that asks an LLM endpoint which tool to call next.

    ``tool_mode`` selects how tools are exposed: ``json`` (prompt-embedded,
    default), ``native`` (OpenAI ``tools=[...]``), or ``anthropic``
    (``tool_use``). See the module docstring for the per-mode call path.
    """

    registry: ToolRegistry
    role: str
    base_url: str
    model: str
    max_tokens: int
    api_key: str | None = None
    provider: str = "openai"
    model_context_length: int | None = None
    model_capabilities: list[str] = field(default_factory=list)
    tool_mode: str = "json"

    input_tokens: int = 0
    output_tokens: int = 0

    def _system_prompt(self) -> str:
        return _SYSTEM_PREAMBLE + "\n" + self.registry.to_prompt_section(self.role)

    def _user_prompt(self, prompt: str, tool_results: list[Any]) -> str:
        if not tool_results:
            return prompt
        # Bounded observation window (#1048): newest results verbatim, older
        # calls collapsed to one-liners so prompt growth is capped.
        older, recent = tool_results[:-_VERBATIM_TAIL], tool_results[-_VERBATIM_TAIL:]
        sections = [f"Original question: {prompt}"]
        if older:
            sections.append("Earlier tool calls (summary):\n" + _digest(older))
        observations = "\n".join(_summarize_result(r) for r in recent)
        sections.append(f"Recent tool observations:\n{observations}")
        sections.append("Decide the next tool call, or give your final answer.")
        return "\n\n".join(sections)

    def _accumulate(self, in_tok: Any, out_tok: Any) -> None:
        self.input_tokens += int(in_tok or 0)
        self.output_tokens += int(out_tok or 0)

    def _decide(self, calls: list[Any], content: str) -> PlanDecision:
        """Pick the first role-permitted tool call, else a plain-text final answer.

        Only calls naming a tool the role may actually use are kept; the executor
        re-checks at dispatch, but filtering here avoids burning a tool-call slot
        on hallucinated names.
        """
        valid = [c for c in calls if self.registry.get(c.name) is not None]
        if valid:
            return PlanDecision(tool_calls=[ToolCall(name=c.name, args=c.arguments) for c in valid[:1]])
        return PlanDecision(final=(content or "").strip())

    async def plan(self, *, prompt: str, tool_results: list[Any]) -> PlanDecision:
        from fleet_platform.services.llm_caller import (
            call_anthropic,
            call_anthropic_tools,
            call_openai_compat,
            call_openai_compat_tools,
        )

        user_prompt = self._user_prompt(prompt, tool_results)

        if self.tool_mode == "native":
            message, in_tok, out_tok = await call_openai_compat_tools(
                base_url=self.base_url,
                api_key=self.api_key,
                model=self.model,
                max_tokens=self.max_tokens,
                system_prompt=_NATIVE_SYSTEM_PREAMBLE,
                user_prompt=user_prompt,
                tools=self.registry.to_openai_tools(self.role),
                history=None,
                model_context_length=self.model_context_length,
                model_capabilities=self.model_capabilities,
            )
            self._accumulate(in_tok, out_tok)
            # extract_tool_calls reads native tool_calls, falling back to
            # content parsing when the endpoint returned none.
            return self._decide(extract_tool_calls(message), message.get("content") or "")

        if self.tool_mode == "anthropic":
            message, in_tok, out_tok = await call_anthropic_tools(
                api_key=self.api_key or "",
                model=self.model,
                max_tokens=self.max_tokens,
                system_prompt=_NATIVE_SYSTEM_PREAMBLE,
                user_prompt=user_prompt,
                tools=self.registry.to_anthropic_tools(self.role),
                history=None,
                model_context_length=self.model_context_length,
            )
            self._accumulate(in_tok, out_tok)
            return self._decide(extract_tool_calls(message), message.get("content") or "")

        # Default json (prompt-embedded) path — unchanged behaviour.
        system_prompt = self._system_prompt()
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

        self._accumulate(in_tok, out_tok)
        return self._decide(parse_tool_calls_from_content(content or ""), content or "")
