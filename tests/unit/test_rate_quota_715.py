"""Rate / quota / cap invariants for the agent (#715).

Pins every hard bound so a regression that loosens a limit fails loudly:
6 iterations · 12 tool calls/turn · 4 KB tool-result cap · 4 h approval expiry ·
5 MB session / 50 MB user / 64 KB artifact quotas · co-sign at > 8 targets.
"""

from __future__ import annotations

from datetime import timedelta


def test_loop_iteration_and_call_bounds():
    from fleet_platform.agent import loop

    assert loop.MAX_ITERATIONS == 6
    assert loop.MAX_TOOL_CALLS == 12


def test_tool_result_cap():
    from fleet_platform.agent.planner import TOOL_RESULT_CAP

    assert TOOL_RESULT_CAP == 4096


def test_quarantine_quotas():
    from fleet_platform.services import agent_quarantine as q

    assert q.SESSION_QUOTA_BYTES == 5 * 1024 * 1024
    assert q.USER_QUOTA_BYTES == 50 * 1024 * 1024
    assert q.ARTIFACT_MAX_BYTES == 64 * 1024
    assert q.TTL_SECONDS == 24 * 60 * 60


def test_validation_size_cap():
    from fleet_platform.services.artifact_validation import MAX_BYTES

    assert MAX_BYTES == 64 * 1024


def test_approval_window_is_four_hours():
    from fleet_platform.services.agent_apply_svc import APPROVAL_TTL

    assert APPROVAL_TTL == timedelta(hours=4)


def test_cosign_threshold_is_eight():
    from fleet_platform.models.pending_action import PendingAction

    assert PendingAction.CO_SIGN_THRESHOLD == 8


def test_prompt_input_cap_is_bounded():
    from fleet_platform.api.routes.agent import AgentRunRequest

    field = AgentRunRequest.model_fields["prompt"]
    # The prompt must carry a finite, bounded length cap (<= 32K input ceiling).
    max_len = next((m.max_length for m in field.metadata if getattr(m, "max_length", None)), None)
    assert max_len is not None and 0 < max_len <= 32_768


def test_run_route_rate_limited_six_per_minute():
    from fleet_platform.api.limiter import limiter
    from fleet_platform.api.routes import agent

    # Behavioral: assert the SlowAPI limiter actually registered a 6/minute limit
    # for the streaming run route (#715), instead of grepping the source for the
    # decorator text. _route_limits is keyed by "<module>.<func>" and is populated
    # only when the @limiter.limit decorator executes at import time, so this fails
    # if the decorator is removed or the rate is changed.
    key = f"{agent.run_agent_stream.__module__}.{agent.run_agent_stream.__name__}"
    windows = {(lim.limit.amount, lim.limit.GRANULARITY.seconds) for lim in limiter._route_limits.get(key, [])}
    assert (6, 60) in windows, f"run_agent_stream must register a 6/minute rate limit; got {windows}"
