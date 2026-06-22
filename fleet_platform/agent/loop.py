"""Bounded agent loop (#711).

Drives planner ↔ executor until the planner returns a final answer or a hard
bound trips. Yields a stream of `AgentEvent`s the route serializes to SSE. The
loop is intentionally LLM-agnostic: it depends only on a `Planner` protocol, so
it is fully unit-testable with a scripted planner and never blocks on a model.

Hard bounds (a confused planner fails loudly, never loops — #716):
- MAX_ITERATIONS = 6
- MAX_TOOL_CALLS = 12 per run
- client-disconnect check before every iteration
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from fleet_platform.agent.executor import AWAITING_APPROVAL, Executor
from fleet_platform.agent.registry import ToolCtx

MAX_ITERATIONS = 6
MAX_TOOL_CALLS = 12

# Tools whose successful result satisfies the "dry-run first" gate for live tools.
DRY_RUN_TOOLS = frozenset({"apply_salt_state_dry_run", "dry_run_artifact"})


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

            for call in decision.tool_calls:
                if total_calls >= self.max_tool_calls:
                    yield AgentEvent("limit_reached", {"limit": "max_tool_calls", "value": self.max_tool_calls})
                    return
                total_calls += 1
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

        yield AgentEvent("limit_reached", {"limit": "max_iterations", "value": self.max_iterations})
