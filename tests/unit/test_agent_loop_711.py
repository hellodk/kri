"""#711 Phase B — bounded agent loop event stream + hard limits."""

import uuid

from fleet_platform.agent.executor import Executor
from fleet_platform.agent.loop import AgentLoop, PlanDecision, ToolCall
from fleet_platform.agent.registry import ToolCtx, ToolRegistry, ToolSpec

SCHEMA = {"type": "object", "additionalProperties": False, "properties": {"x": {"type": "string"}}}


class ScriptedPlanner:
    """Returns a pre-baked sequence of PlanDecisions, one per plan() call."""

    def __init__(self, decisions):
        self._decisions = list(decisions)
        self.calls = 0

    async def plan(self, *, prompt, history, tool_results):
        d = self._decisions[self.calls] if self.calls < len(self._decisions) else PlanDecision(final="done")
        self.calls += 1
        return d


async def _echo(ctx, **kw):
    return {"echo": kw}


def _registry(**overrides):
    r = ToolRegistry()
    r.register(
        ToolSpec(
            name="get_node",
            description="d",
            params_schema=SCHEMA,
            required_role="viewer",
            handler=_echo,
            **overrides,
        )
    )
    return r


def _ctx():
    return ToolCtx(actor="alice@org", role="operator", session_id=uuid.uuid4())


async def _drain(loop, prompt="hi"):
    return [ev async for ev in loop.run(prompt)]


async def test_immediate_final():
    loop = AgentLoop(Executor(_registry()), ScriptedPlanner([PlanDecision(final="hello")]), _ctx())
    events = await _drain(loop)
    types = [e.type for e in events]
    assert types == ["step_start", "final"]
    assert events[-1].data["text"] == "hello"


async def test_single_tool_then_final():
    planner = ScriptedPlanner(
        [PlanDecision(tool_calls=[ToolCall("get_node", {"x": "n1"})]), PlanDecision(final="answer")]
    )
    loop = AgentLoop(Executor(_registry()), planner, _ctx())
    types = [e.type for e in await _drain(loop)]
    assert types == ["step_start", "tool_call", "tool_result", "step_start", "final"]


async def test_tool_result_carries_executor_output():
    planner = ScriptedPlanner([PlanDecision(tool_calls=[ToolCall("get_node", {"x": "n1"})]), PlanDecision(final="ok")])
    loop = AgentLoop(Executor(_registry()), planner, _ctx())
    events = await _drain(loop)
    tr = next(e for e in events if e.type == "tool_result")
    assert tr.data["ok"] is True
    assert tr.data["result"] == {"echo": {"x": "n1"}}


async def test_max_iterations_limit():
    # planner always asks for a tool, never finalizes → must stop at max_iterations
    planner = ScriptedPlanner([PlanDecision(tool_calls=[ToolCall("get_node", {"x": str(i)})]) for i in range(20)])
    loop = AgentLoop(Executor(_registry()), planner, _ctx(), max_iterations=3)
    events = await _drain(loop)
    assert events[-1].type == "limit_reached"
    assert events[-1].data["limit"] == "max_iterations"
    assert sum(1 for e in events if e.type == "step_start") == 3


async def test_max_tool_calls_limit():
    planner = ScriptedPlanner([PlanDecision(tool_calls=[ToolCall("get_node", {"x": str(i)}) for i in range(10)])])
    loop = AgentLoop(Executor(_registry()), planner, _ctx(), max_tool_calls=4)
    events = await _drain(loop)
    assert events[-1].type == "limit_reached"
    assert events[-1].data["limit"] == "max_tool_calls"
    assert sum(1 for e in events if e.type == "tool_call") == 4


async def test_awaiting_approval_halts_loop():
    planner = ScriptedPlanner(
        [PlanDecision(tool_calls=[ToolCall("get_node", {"x": "n"})]), PlanDecision(final="never reached")]
    )
    loop = AgentLoop(Executor(_registry(requires_approval=True)), planner, _ctx())
    events = await _drain(loop)
    assert events[-1].type == "awaiting_approval"
    assert not any(e.type == "tool_result" for e in events)


async def test_client_disconnect_aborts_before_iteration():
    loop = AgentLoop(
        Executor(_registry()),
        ScriptedPlanner([PlanDecision(final="x")]),
        _ctx(),
        should_stop=lambda: True,
    )
    events = await _drain(loop)
    assert events == events[:1] and events[0].type == "aborted"


async def test_empty_decision_ends_cleanly():
    loop = AgentLoop(Executor(_registry()), ScriptedPlanner([PlanDecision()]), _ctx())
    types = [e.type for e in await _drain(loop)]
    assert types == ["step_start", "final"]
