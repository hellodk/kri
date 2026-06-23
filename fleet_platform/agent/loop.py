"""Bounded agent loop (#711).

Drives planner ↔ executor until the planner returns a final answer or a hard
bound trips. Yields a stream of `AgentEvent`s the route serializes to SSE. The
loop is intentionally LLM-agnostic: it depends only on a `Planner` protocol, so
it is fully unit-testable with a scripted planner and never blocks on a model.

Hard bounds (a confused planner fails loudly, never loops — #716):
- MAX_ITERATIONS = 6
- MAX_TOOL_CALLS = 12 per run
- NO-PROGRESS guard: a planner that only re-requests tool calls it has already
  made (same name + args) is stuck; stop immediately instead of burning every
  iteration on an identical lookup (a weak model would otherwise repeat one
  rag_search 6× and time out with no answer).
- client-disconnect check before every iteration

Every bounded/stalled stop still emits a terminal ``final`` event so the caller
is never left with no answer — only the "Stopped: reached ..." note.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from fleet_platform.agent.executor import AWAITING_APPROVAL, Executor
from fleet_platform.agent.registry import ToolCtx

MAX_ITERATIONS = 6
MAX_TOOL_CALLS = 12

# Tools whose successful result satisfies the "dry-run first" gate for live tools.
DRY_RUN_TOOLS = frozenset({"apply_salt_state_dry_run", "dry_run_artifact"})


def _call_signature(name: str, args: dict[str, Any]) -> str:
    """Stable identity for a tool call so identical repeats can be detected."""
    try:
        arg_repr = json.dumps(args, sort_keys=True, default=str)
    except (TypeError, ValueError):
        arg_repr = repr(sorted((str(k), str(v)) for k, v in (args or {}).items()))
    return f"{name}:{arg_repr}"


def _stall_message(reason: str | None, results_gathered: int) -> str:
    """A concise, honest answer for a bounded/stalled run (never domain-specific).

    The loop is LLM-agnostic, so this stays generic: it explains why the run
    stopped and tells the operator how to make progress, rather than pretending
    to have an answer it never reached.
    """
    lead = {
        "no_progress": ("I stopped because I kept repeating the same lookup without getting new information."),
        "max_iterations": "I hit the reasoning-step limit before reaching a definitive answer.",
        "max_tool_calls": "I hit the tool-call limit before reaching a definitive answer.",
    }.get(reason or "", "I stopped before reaching a definitive answer.")

    if results_gathered:
        tail = (
            f" I gathered {results_gathered} tool result(s) but couldn't conclude. Try rephrasing the "
            "question, narrowing it to a specific node or group by name, or confirming the relevant "
            "data is indexed."
        )
    else:
        tail = (
            " I couldn't gather any useful information with the available read-only tools. Try "
            "rephrasing the question or naming a specific node or group."
        )
    return lead + tail


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlanDecision:
    """Either a final answer (``final`` set) or a batch of tool calls."""

    final: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


class Planner(Protocol):
    async def plan(self, *, prompt: str, history: list[dict], tool_results: list[Any]) -> PlanDecision: ...


@dataclass
class AgentEvent:
    type: str  # step_start|tool_call|tool_result|awaiting_approval|final|limit_reached|aborted
    data: dict[str, Any] = field(default_factory=dict)


class AgentLoop:
    def __init__(
        self,
        executor: Executor,
        planner: Planner,
        ctx: ToolCtx,
        *,
        max_iterations: int = MAX_ITERATIONS,
        max_tool_calls: int = MAX_TOOL_CALLS,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        self.executor = executor
        self.planner = planner
        self.ctx = ctx
        self.max_iterations = max_iterations
        self.max_tool_calls = max_tool_calls
        self.should_stop = should_stop

    async def run(self, prompt: str) -> AsyncIterator[AgentEvent]:
        history: list[dict] = []
        tool_results: list[Any] = []
        total_calls = 0
        last_dry_run: Any = None
        seen_calls: set[str] = set()
        stop_reason: str | None = None
        stop_value = 0

        for iteration in range(1, self.max_iterations + 1):
            if self.should_stop is not None and self.should_stop():
                yield AgentEvent("aborted", {"reason": "client_disconnect", "iteration": iteration})
                return

            yield AgentEvent("step_start", {"iteration": iteration})
            decision = await self.planner.plan(prompt=prompt, history=history, tool_results=tool_results)

            if decision.final is not None:
                yield AgentEvent("final", {"text": decision.final, "iterations": iteration})
                return

            if not decision.tool_calls:
                # Planner produced neither tools nor a final answer — end cleanly.
                yield AgentEvent("final", {"text": "", "iterations": iteration})
                return

            progressed = False
            for call in decision.tool_calls:
                sig = _call_signature(call.name, call.args)
                if sig in seen_calls:
                    # The planner re-requested an identical call. Re-running it
                    # yields the same result, so skip it rather than burn a tool
                    # slot; if the whole decision is duplicates we stall out below.
                    continue
                if total_calls >= self.max_tool_calls:
                    stop_reason, stop_value = "max_tool_calls", self.max_tool_calls
                    break
                total_calls += 1
                seen_calls.add(sig)
                progressed = True
                yield AgentEvent("tool_call", {"name": call.name, "args": call.args, "n": total_calls})

                result = await self.executor.dispatch(call.name, call.args, self.ctx)

                if result.status == AWAITING_APPROVAL:
                    # The route turns this into a PendingAction carrying the
                    # captured dry-run output for the approver to review.
                    yield AgentEvent(
                        "awaiting_approval",
                        {
                            "name": call.name,
                            "args": call.args,
                            "n": total_calls,
                            "dry_run_result": last_dry_run,
                        },
                    )
                    return

                # A successful dry-run satisfies the dry-run-first gate for the
                # subsequent live tool and is captured for the approval email.
                if call.name in DRY_RUN_TOOLS and result.ok:
                    self.ctx.extra["dry_run_done"] = True
                    last_dry_run = result.result

                tool_results.append(result)
                history.append({"tool": call.name, "args": call.args, "ok": result.ok})
                yield AgentEvent(
                    "tool_result",
                    {
                        "name": call.name,
                        "ok": result.ok,
                        "status": result.status,
                        "result": result.result,
                        "error": result.error,
                        "cached": result.cached,
                    },
                )

            if stop_reason is not None:
                break
            if not progressed:
                # Every call in this decision was a repeat — the planner is stuck.
                stop_reason, stop_value = "no_progress", total_calls
                break
        else:
            stop_reason, stop_value = "max_iterations", self.max_iterations

        # A bounded/stalled stop: surface telemetry, then ALWAYS hand back a
        # plain-text answer so the caller never sees a silent dead end.
        yield AgentEvent("limit_reached", {"limit": stop_reason, "value": stop_value})
        yield AgentEvent(
            "final",
            {
                "text": _stall_message(stop_reason, len(tool_results)),
                "iterations": self.max_iterations,
                "stalled": True,
            },
        )
