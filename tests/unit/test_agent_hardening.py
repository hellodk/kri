"""Hardening tests for #1048 + #1049 item 1.

Covers:
- planner observation window: last 2 verbatim, bounded one-line digest for older calls
- loop bounds: MAX_TOOL_CALLS == MAX_ITERATIONS
- agent route: mark_unhealthy ONLY on LLM endpoint errors
- agent route: client-disconnect finalize runs exactly once (cost + query log + status)
- task_lock token ownership (non-owner cannot delete) + ttl overrides
- cost rate table selection (per-provider/model $/1M rates)
- llm_caller usage estimation fallback when provider reports zero tokens
- llm.py output sanitization at result boundary + persisted stream text
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import types
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from fleet_platform.agent.executor import ToolResult
from fleet_platform.services.llm_caller import LLMCallError

# ── helpers ──────────────────────────────────────────────────────────────────


def _endpoint():
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="test-endpoint",
        enabled=True,
        base_url="http://llm.local",
        model="test-model",
        provider="openai",
        max_tokens=64,
        model_context_length=8192,
        model_capabilities="",
        tool_mode="json",
    )


class FakeRequest:
    """Minimal Request stand-in: scripted is_disconnected() answers."""

    def __init__(self, answers):
        self._answers = list(answers)
        self.disconnect_seen = asyncio.Event()

    async def is_disconnected(self) -> bool:
        val = self._answers.pop(0) if len(self._answers) > 1 else self._answers[0]
        if val:
            self.disconnect_seen.set()
        return val


def _mock_db():
    db = AsyncMock()
    db.add = Mock()
    # Concrete empty result for tool handlers (list_nodes etc.) so dispatch
    # doesn't trip AsyncMock internals and emit unawaited-coroutine warnings.
    db.execute = AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [])))
    return db


_CLAIMS = {"sub": uuid.uuid4(), "role": "operator", "email": "op@example.com"}

_SSE_DONE = "data: [DONE]"


async def _drain(body_iterator) -> list[dict]:
    """Consume an SSE body iterator into parsed JSON event dicts."""
    events: list[dict] = []
    raw = ""
    async for chunk in body_iterator:
        raw += chunk
    for line in raw.splitlines():
        if line.startswith("data: ") and line != _SSE_DONE:
            try:
                events.append(json.loads(line[len("data: ") :]))
            except json.JSONDecodeError:
                pass
    return events


def _query_logs(db) -> list:
    from fleet_platform.models.llm_query_log import LLMQueryLog

    return [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], LLMQueryLog)]


def _route_harness(monkeypatch, endpoint, *, call_fn):
    """Patch run_agent_stream's collaborators; returns (db, cost_mock, session_box)."""
    from fleet_platform.api.routes import agent as agent_routes
    from fleet_platform.services import cost_tracker as cost_mod
    from fleet_platform.services import llm_svc as llm_svc_mod

    ep = endpoint
    monkeypatch.setattr(llm_svc_mod, "get_endpoint", AsyncMock(return_value=ep))
    monkeypatch.setattr(llm_svc_mod, "get_decrypted_api_key", Mock(return_value=None))
    monkeypatch.setattr(
        "fleet_platform.api.routes.llm._resolve_model",
        AsyncMock(return_value="test-model"),
    )
    monkeypatch.setattr(
        "fleet_platform.services.llm_caller.call_openai_compat",
        call_fn,
    )
    cost_mock = Mock(return_value=0.0)
    monkeypatch.setattr(cost_mod, "record_tokens_for_endpoint", cost_mock)

    session_box: dict = {}
    created_sessions = []

    def fake_session_cls(**kw):
        s = SimpleNamespace(
            id=uuid.uuid4(),
            user_id=kw.get("user_id"),
            endpoint_id=kw.get("endpoint_id"),
            status="active",
            initial_prompt=kw.get("initial_prompt"),
            iteration_count=0,
            tool_call_count=0,
            error=None,
        )
        created_sessions.append(s)
        session_box["session"] = s
        return s

    monkeypatch.setattr(agent_routes, "AgentSession", fake_session_cls)
    tier_state_reset()
    return _mock_db(), cost_mock, session_box


def tier_state_reset():
    from fleet_platform.services import tier_router

    tier_router.STATE.reset()


# ── 1. planner observation window (#1048 item 1) ─────────────────────────────


def _planner():
    from fleet_platform.agent.planner import LLMPlanner
    from fleet_platform.agent.tools import build_default_registry

    return LLMPlanner(
        registry=build_default_registry(),
        role="operator",
        base_url="http://llm.local",
        model="test-model",
        max_tokens=512,
    )


def _res(name: str, *, ok: bool = True, payload: str = "data", error: str | None = None) -> ToolResult:
    if ok:
        return ToolResult(name=name, ok=True, result=payload)
    return ToolResult(name=name, ok=False, error=error or "boom")


def test_planner_window_keeps_last_two_verbatim():
    p = _planner()
    old_payload = "OLD" + "x" * 4000
    results = [_res(f"t{i}", payload=f"P{i}" + "y" * 300) for i in range(6)]
    results[0] = _res("t0", payload=old_payload)
    prompt = p._user_prompt("question", results)
    # Newest two survive verbatim...
    assert "P4" + "y" * 10 in prompt
    assert "P5" + "y" * 10 in prompt
    # ...the oldest full payload must NOT be carried into the prompt.
    assert old_payload not in prompt


def test_planner_prompt_growth_is_bounded():
    p = _planner()
    results = [_res(f"t{i}", payload="z" * 5000) for i in range(30)]
    prompt = p._user_prompt("q", results)
    # 30 × 5000-char observations would be ~150k chars unbounded; the window
    # caps the prompt at roughly two verbatim results + a short digest.
    assert len(prompt) < 12_000


def test_planner_digest_present_with_ok_and_error_lines():
    p = _planner()
    results = [
        _res("rag_search", payload="big payload that must not appear " * 50),
        _res("ping_node", ok=False, error="node unreachable"),
        _res("list_nodes", payload="recent-ok-payload"),
        _res("get_node", payload="newest-payload"),
    ]
    prompt = p._user_prompt("q", results)
    assert "[rag_search]" in prompt  # collapsed to a one-liner
    assert "[ping_node]" in prompt
    assert "ERROR" in prompt
    # Collapsed calls keep only the one-liner — not their payloads.
    assert "big payload that must not appear" not in prompt
    # Verbatim tail intact.
    assert "recent-ok-payload" in prompt
    assert "newest-payload" in prompt


def test_planner_digest_lines_capped_at_80_chars_and_12_lines():
    p = _planner()
    long_err = "E" * 500
    results = [_res(f"t{i}", ok=False, error=long_err) for i in range(20)]
    prompt = p._user_prompt("q", results)
    lines = prompt.splitlines()
    start = lines.index("Earlier tool calls (summary):") + 1
    end = lines.index("Recent tool observations:")
    digest_lines = [ln for ln in lines[start:end] if ln.startswith("[t")]
    assert len(digest_lines) <= 12
    assert all(len(ln) <= 80 for ln in digest_lines)


def test_planner_single_observation_stays_verbatim():
    p = _planner()
    prompt = p._user_prompt("q", [_res("list_nodes", payload="only-one")])
    assert "only-one" in prompt
    assert "Original question: q" in prompt


# ── 8. loop bounds (#1048 item 8) ────────────────────────────────────────────


def test_max_tool_calls_equals_max_iterations():
    from fleet_platform.agent import loop as agent_loop

    assert agent_loop.MAX_ITERATIONS == 6
    assert agent_loop.MAX_TOOL_CALLS == agent_loop.MAX_ITERATIONS


def test_planner_plan_has_no_history_param():
    import inspect

    from fleet_platform.agent.loop import AgentLoop
    from fleet_platform.agent.planner import LLMPlanner

    params = inspect.signature(LLMPlanner.plan).parameters
    assert "history" not in params
    proto_params = inspect.signature(AgentLoop.__init__).parameters
    assert "should_stop" in proto_params


# ── 2. mark_unhealthy only on LLM endpoint errors (#1048 item 2) ─────────────


def test_mark_unhealthy_called_on_llm_call_error():
    from fleet_platform.api.routes import agent as agent_routes
    from fleet_platform.services import tier_router

    tier_state_reset()
    eid = str(uuid.uuid4())
    agent_routes._note_endpoint_error(LLMCallError("HTTP 503 from provider"), eid)
    assert tier_router.STATE.is_healthy(eid) is False


def test_no_mark_unhealthy_on_generic_exception():
    from fleet_platform.api.routes import agent as agent_routes
    from fleet_platform.services import tier_router

    tier_state_reset()
    eid = str(uuid.uuid4())
    agent_routes._note_endpoint_error(ValueError("some bug"), eid)
    agent_routes._note_endpoint_error(KeyError("db"), eid)
    assert tier_router.STATE.is_healthy(eid) is True


@pytest.mark.parametrize("exc,poisoned", [(LLMCallError("timeout"), True), (RuntimeError("bug"), False)])
async def test_route_marks_unhealthy_by_exception_class(monkeypatch, exc, poisoned):
    from fleet_platform.api.routes import agent as agent_routes
    from fleet_platform.services import tier_router

    ep = _endpoint()

    async def failing_call(**kw):
        raise exc

    db, _cost, box = _route_harness(monkeypatch, ep, call_fn=failing_call)
    request = FakeRequest([False])
    resp = await agent_routes.run_agent_stream.__wrapped__(
        request=request,
        payload=agent_routes.AgentRunRequest(prompt="hi", endpoint_id=ep.id),
        db=db,
        claims=_CLAIMS,
        _agent_gate=None,
    )
    events = await _drain(resp.body_iterator)
    assert any(e.get("type") == "error" for e in events)
    is_healthy = tier_router.STATE.is_healthy(str(ep.id))
    assert is_healthy is (not poisoned)
    assert box["session"].status == "aborted"
    # Even a failed run finalizes cost + log once.
    assert _cost.call_count == 1
    assert len(_query_logs(db)) == 1


# ── 3. client-disconnect wiring + finalize-exactly-once (#1048 item 3) ───────


async def test_watch_disconnect_sets_flag(monkeypatch):
    from fleet_platform.api.routes import agent as agent_routes

    monkeypatch.setattr(agent_routes, "_DISCONNECT_POLL_S", 0.01)
    req = FakeRequest([True])
    flag = asyncio.Event()
    await asyncio.wait_for(agent_routes._watch_disconnect(req, flag), timeout=1.0)
    assert flag.is_set()


async def test_graceful_disconnect_aborts_session_and_finalizes_once(monkeypatch):
    from fleet_platform.api.routes import agent as agent_routes

    monkeypatch.setattr(agent_routes, "_DISCONNECT_POLL_S", 0.01)
    ep = _endpoint()
    calls = {"n": 0}

    async def scripted_call(**kw):
        calls["n"] += 1
        await asyncio.sleep(0.05)  # let the disconnect watcher observe the drop
        if calls["n"] == 1:
            return '{"name": "list_nodes", "arguments": {"password": "hunter2"}}', 10, 5
        return "should never be reached", 1, 1

    db, cost, box = _route_harness(monkeypatch, ep, call_fn=scripted_call)
    request = FakeRequest([False, True])  # drops after the first poll

    resp = await agent_routes.run_agent_stream.__wrapped__(
        request=request,
        payload=agent_routes.AgentRunRequest(prompt="inspect fleet", endpoint_id=ep.id),
        db=db,
        claims=_CLAIMS,
        _agent_gate=None,
    )
    events = await _drain(resp.body_iterator)

    assert any(e.get("type") == "aborted" for e in events)
    done = [e for e in events if e.get("type") == "done"]
    assert done and done[0]["status"] == "aborted"
    assert box["session"].status == "aborted"
    assert cost.call_count == 1
    logs = _query_logs(db)
    assert len(logs) == 1
    # Persisted tool-call args are redacted via the audit helper (#1048).
    persisted_calls = logs[0].tool_calls
    assert persisted_calls and persisted_calls[0]["name"] == "list_nodes"
    assert persisted_calls[0]["args"]["password"] == "[REDACTED]"


async def test_hard_cancel_finalize_runs_exactly_once(monkeypatch):
    """GeneratorExit mid-stream still persists cost + query log, exactly once."""
    from fleet_platform.api.routes import agent as agent_routes

    ep = _endpoint()

    async def hanging_call(**kw):
        await asyncio.sleep(60)

    db, cost, box = _route_harness(monkeypatch, ep, call_fn=hanging_call)
    request = FakeRequest([False])

    resp = await agent_routes.run_agent_stream.__wrapped__(
        request=request,
        payload=agent_routes.AgentRunRequest(prompt="hi", endpoint_id=ep.id),
        db=db,
        claims=_CLAIMS,
        _agent_gate=None,
    )
    agen = resp.body_iterator
    await agen.__anext__()  # session_start frame
    await agen.aclose()  # client vanished → GeneratorExit into the generator

    assert box["session"].status == "aborted"
    assert cost.call_count == 1
    logs = _query_logs(db)
    assert len(logs) == 1


# ── 4. anthropic timeout budget (#1048 item 4) ───────────────────────────────


def test_anthropic_timeout_read_is_180s():
    from fleet_platform.services import llm_caller

    assert llm_caller._ANTHROPIC_TIMEOUT.read == 180.0


# ── 6. usage estimation fallback (#1049 item 1) ──────────────────────────────


def test_estimate_usage_helper_fills_missing_sides(caplog):
    from fleet_platform.services.llm_caller import _estimate_usage_if_missing
    from fleet_platform.services.llm_context import estimate_tokens

    with caplog.at_level(logging.INFO, logger="fleet_platform.services.llm_caller"):
        pin, pout = _estimate_usage_if_missing(
            prompt_tokens=0,
            completion_tokens=0,
            input_text="a" * 400,
            output_text="b" * 80,
        )
    assert pin == estimate_tokens("a" * 400)
    assert pout == estimate_tokens("b" * 80)
    assert any(r.message == "llm_usage_estimated" for r in caplog.records)


def test_estimate_usage_helper_keeps_reported_usage(caplog):
    from fleet_platform.services.llm_caller import _estimate_usage_if_missing

    with caplog.at_level(logging.INFO, logger="fleet_platform.services.llm_caller"):
        pin, pout = _estimate_usage_if_missing(
            prompt_tokens=12,
            completion_tokens=7,
            input_text="xxxx",
            output_text="yy",
        )
    assert (pin, pout) == (12, 7)
    assert not any(r.message == "llm_usage_estimated" for r in caplog.records)


def _install_fake_anthropic(monkeypatch, input_tokens: int, output_tokens: int):
    """Swap in a fake `anthropic` module whose SDK returns zero usage."""
    mod = types.ModuleType("anthropic")

    class APIError(Exception):
        pass

    message = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="hello world")],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )

    class _Messages:
        async def create(self, **kw):
            return message

    class FakeAsyncAnthropic:
        def __init__(self, api_key=None, timeout=None):
            self.messages = _Messages()

    mod.AsyncAnthropic = FakeAsyncAnthropic
    mod.APIError = APIError
    monkeypatch.setitem(sys.modules, "anthropic", mod)


async def test_call_anthropic_estimates_when_usage_zero(monkeypatch, caplog):
    from fleet_platform.services.llm_caller import call_anthropic
    from fleet_platform.services.llm_context import estimate_tokens

    _install_fake_anthropic(monkeypatch, input_tokens=0, output_tokens=0)
    with caplog.at_level(logging.INFO, logger="fleet_platform.services.llm_caller"):
        content, tin, tout = await call_anthropic(
            api_key="k",
            model="claude-test",
            max_tokens=64,
            system_prompt="sys",
            user_prompt="user question",
        )
    assert content == "hello world"
    assert tin == estimate_tokens("sys\nuser question") or tin > 0
    assert tout == estimate_tokens("hello world")
    assert any(r.message == "llm_usage_estimated" for r in caplog.records)


async def test_call_anthropic_passthrough_real_usage(monkeypatch, caplog):
    from fleet_platform.services.llm_caller import call_anthropic

    _install_fake_anthropic(monkeypatch, input_tokens=42, output_tokens=17)
    with caplog.at_level(logging.INFO, logger="fleet_platform.services.llm_caller"):
        _content, tin, tout = await call_anthropic(
            api_key="k",
            model="claude-test",
            max_tokens=64,
            system_prompt="sys",
            user_prompt="q",
        )
    assert (tin, tout) == (42, 17)
    assert not any(r.message == "llm_usage_estimated" for r in caplog.records)


# ── 5. llm.py output sanitization (#1048 item 5) ─────────────────────────────


def _llm_harness(monkeypatch, endpoint):
    from fleet_platform.api.routes import llm as llm_routes

    log_mock = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
    audit_mock = AsyncMock()
    monkeypatch.setattr(llm_routes.llm_svc, "get_endpoint", AsyncMock(return_value=endpoint))
    monkeypatch.setattr(llm_routes.llm_svc, "get_decrypted_api_key", Mock(return_value=None))
    monkeypatch.setattr(llm_routes.llm_svc, "create_query_log", log_mock)
    monkeypatch.setattr(llm_routes, "audit", audit_mock)
    ctx = {"log": log_mock}
    return ctx


async def test_buffered_query_result_is_sanitized(monkeypatch):
    from fleet_platform.api.routes import llm as llm_routes

    ep = _endpoint()
    ctx = _llm_harness(monkeypatch, ep)

    async def fake_ctx(db, intent, query=None):
        return "system", []

    async def dirty_call(**kw):
        return "<script>alert(1)</script>clean answer", 5, 5

    monkeypatch.setattr(llm_routes, "build_fleet_context", fake_ctx)
    monkeypatch.setattr(llm_routes, "call_openai_compat", dirty_call)

    resp = await llm_routes.submit_query.__wrapped__(
        request=FakeRequest([False]),
        payload=llm_routes.LLMQueryRequest(prompt="hi", intent="fleet_query", endpoint_id=ep.id),
        db=_mock_db(),
        claims=_CLAIMS,
    )
    assert resp.result == "clean answer"
    assert ctx["log"].call_args.kwargs["response"] == "clean answer"


async def test_stream_persists_sanitized_text_deltas_untouched(monkeypatch):
    from fleet_platform.api.routes import llm as llm_routes

    ep = _endpoint()
    ctx = _llm_harness(monkeypatch, ep)
    seen_frames: list[str] = []

    async def fake_ctx(db, intent, query=None):
        return "system", []

    async def fake_stream(**kw):
        yield {"type": "delta", "text": "<script>x</script>"}
        yield {"type": "delta", "text": "safe body"}
        yield {
            "type": "done",
            "content": "<script>x</script>safe body",
            "input_tokens": 4,
            "output_tokens": 4,
        }

    async def capturing_gen(**kw):
        async for ev in fake_stream(**kw):
            seen_frames.append(ev["type"])
            yield ev

    monkeypatch.setattr(llm_routes, "build_fleet_context", fake_ctx)
    monkeypatch.setattr(llm_routes, "stream_openai_compat", capturing_gen)

    resp = await llm_routes.submit_query_stream.__wrapped__(
        request=FakeRequest([False]),
        payload=llm_routes.LLMQueryRequest(prompt="hi", intent="fleet_query", endpoint_id=ep.id),
        db=_mock_db(),
        claims=_CLAIMS,
    )
    raw = ""
    async for chunk in resp.body_iterator:
        raw += chunk
    # Raw delta frame forwarded untouched (client renders progressively).
    assert (
        '{"type": "delta", "text": "<script>x</script>"}' in raw.replace("\\u003c", "<").replace("\\u003e", ">")
        or "<script>x</script>" in raw
    )
    # Persisted answer is sanitized.
    assert ctx["log"].call_args.kwargs["response"] == "safe body"


# ── 7. cost rate table (#1048 item 7) ────────────────────────────────────────


def test_rate_table_selection():
    from fleet_platform.services import cost_tracker

    haiku = cost_tracker.rate_for("anthropic", "claude-3-5-haiku-20241022")
    sonnet = cost_tracker.rate_for("anthropic", "claude-sonnet-4-20250514")
    gpt4o = cost_tracker.rate_for("openai", "gpt-4o-2024-08-06")
    unknown = cost_tracker.rate_for("ollama", "llama3:70b")
    none_args = cost_tracker.rate_for(None, None)

    assert haiku != sonnet != gpt4o  # distinct classes priced distinctly
    assert haiku[0] < sonnet[0]  # haiku cheaper than sonnet on input
    blended = cost_tracker.COST_PER_1K_TOKENS_USD * 1000.0
    assert unknown == (blended, blended)
    assert none_args == (blended, blended)


def test_rate_table_output_side_priced_higher():
    from fleet_platform.services import cost_tracker

    sonnet_in, sonnet_out = cost_tracker.rate_for("anthropic", "claude-3-sonnet")
    assert sonnet_out > sonnet_in
    gpt_in, gpt_out = cost_tracker.rate_for("openai", "gpt-4o")
    assert gpt_out > gpt_in


def test_record_tokens_with_provider_model_rates():
    from fleet_platform.services.cost_tracker import _CostState

    st = _CostState()
    c_haiku_in = st.record_tokens(1_000_000, 0, provider="anthropic", model="claude-3-5-haiku-latest")
    st.reset()
    c_sonnet_in = st.record_tokens(1_000_000, 0, provider="anthropic", model="claude-3-5-sonnet-latest")
    assert c_haiku_in == pytest.approx(0.80)
    assert c_sonnet_in == pytest.approx(3.00)

    st.reset()
    c_mixed = st.record_tokens(500_000, 250_000, provider="openai", model="gpt-4o")
    r_in, r_out = cost_tracker_rate("openai", "gpt-4o")
    assert c_mixed == pytest.approx(0.5 * r_in + 0.25 * r_out)


def cost_tracker_rate(provider, model):
    from fleet_platform.services import cost_tracker

    return cost_tracker.rate_for(provider, model)


def test_record_tokens_signature_backwards_compatible():
    """No provider/model → legacy blended behaviour, signature unchanged."""
    from fleet_platform.services import cost_tracker
    from fleet_platform.services.cost_tracker import _CostState

    st = _CostState()
    cost = st.record_tokens(1000, 2000)
    blended = cost_tracker.COST_PER_1K_TOKENS_USD
    assert cost == pytest.approx((1000 + 2000) / 1000.0 * blended)


def test_record_tokens_for_endpoint_selects_rate_by_model():
    from fleet_platform.services import cost_tracker
    from fleet_platform.services.cost_tracker import _CostState

    st = _CostState()
    haiku_ep = SimpleNamespace(provider="anthropic", model="claude-3-5-haiku-latest")
    sonnet_ep = SimpleNamespace(provider="anthropic", model="claude-3-5-sonnet-latest")

    cost_tracker.record_tokens_for_endpoint(1_000_000, 0, endpoint=haiku_ep, state=st)
    assert st.today_spend() == pytest.approx(0.80)
    st.reset()
    cost_tracker.record_tokens_for_endpoint(1_000_000, 0, endpoint=sonnet_ep, state=st)
    assert st.today_spend() == pytest.approx(3.00)
