"""#710 Phase A — OTEL agent-span helper degrades gracefully."""

from fleet_platform.core.tracing import agent_span


def test_agent_span_is_a_usable_context_manager():
    with agent_span("test.step") as span:
        # span may be a real span, a no-op span, or None — must never raise
        _ = span


def test_agent_span_accepts_actor_session_tool_and_extra_attrs():
    with agent_span(
        "tool.dispatch",
        actor="alice@org",
        session_id="sess-1",
        tool_name="list_nodes",
        iteration=2,
    ) as span:
        _ = span


def test_agent_span_handles_none_values():
    with agent_span("noop", actor=None, session_id=None, tool_name=None) as span:
        _ = span


def test_agent_span_nests_without_error():
    with agent_span("outer", actor="a@b"):
        with agent_span("inner", actor="a@b", tool_name="get_node"):
            pass
