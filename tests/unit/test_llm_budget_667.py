"""Tests for unified LLM input budgeting + Anthropic robustness (#667).

Covers:
- system + history + user share ONE ceiling (no additive overflow);
- the grounding-rules tail and the user prompt survive truncation;
- the node snapshot annotates when the 50-node cap hides part of the fleet;
- call_anthropic constructs the SDK client with a bounded timeout.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fleet_platform.services.llm_caller import (
    _ANTHROPIC_TIMEOUT,
    _CHARS_PER_TOKEN,
    _budget_inputs,
)
from fleet_platform.services.llm_context import build_static_context


def test_budget_keeps_inputs_under_one_ceiling():
    ctx, max_tokens = 8192, 4096
    system = "S" * 100_000
    history = [{"role": "user", "content": "H" * 50_000} for _ in range(10)]
    user = "U" * 2_000

    new_system, kept = _budget_inputs(
        system_prompt=system, history=history, user_prompt=user, ctx=ctx, max_tokens=max_tokens
    )

    ceiling = (ctx - max_tokens) * _CHARS_PER_TOKEN
    total = len(new_system) + sum(len(m["content"]) for m in kept) + len(user)
    # Total input chars must fit the shared window (with a small marker margin).
    assert total <= ceiling + 500


def test_budget_preserves_user_prompt_and_grounding_tail():
    system = ("HEAD " * 10_000) + "## Rules\n- never wipe disks\n- be idempotent\n"
    new_system, _ = _budget_inputs(
        system_prompt=system,
        history=None,
        user_prompt="how many nodes are offline?",
        ctx=8192,
        max_tokens=4096,
    )
    # The pinned grounding tail must always survive truncation.
    assert "## Rules" in new_system
    assert "be idempotent" in new_system


def test_budget_keeps_only_recent_history():
    history = [{"role": "user", "content": f"msg-{i} " + ("x" * 4000)} for i in range(10)]
    _, kept = _budget_inputs(
        system_prompt="sys",
        history=history,
        user_prompt="q",
        ctx=8192,
        max_tokens=4096,
    )
    # Trimmed to the most recent messages, and the newest is always retained.
    assert len(kept) < len(history)
    assert kept[-1]["content"].startswith("msg-9")


def test_node_snapshot_annotates_when_capped():
    ctx = build_static_context(
        node_count=200,
        online_count=180,
        groups=["g1"],
        salt_master="m",
        playbooks_dir="/p",
        node_records=[
            {
                "hostname": f"h{i}",
                "minion_id": f"m{i}",
                "ip": "1.1.1.1",
                "status": "online",
                "last_seen": "now",
                "group": "—",
            }
            for i in range(50)
        ],
        nodes_shown=50,
    )
    assert "showing the first 50 of 200 nodes" in ctx


def test_node_snapshot_no_annotation_when_complete():
    ctx = build_static_context(
        node_count=3,
        online_count=3,
        groups=["g1"],
        salt_master="m",
        playbooks_dir="/p",
        node_records=[
            {
                "hostname": f"h{i}",
                "minion_id": f"m{i}",
                "ip": "1.1.1.1",
                "status": "online",
                "last_seen": "now",
                "group": "—",
            }
            for i in range(3)
        ],
        nodes_shown=3,
    )
    assert "showing the first" not in ctx


@pytest.mark.asyncio
async def test_call_anthropic_uses_bounded_timeout():
    from fleet_platform.services.llm_caller import call_anthropic

    mock_sdk = MagicMock()
    mock_client_instance = AsyncMock()
    mock_sdk.AsyncAnthropic.return_value = mock_client_instance
    mock_sdk.APIError = type("APIError", (Exception,), {})

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="ok")]
    mock_message.usage.input_tokens = 1
    mock_message.usage.output_tokens = 1
    mock_client_instance.messages.create = AsyncMock(return_value=mock_message)

    with patch.dict("sys.modules", {"anthropic": mock_sdk}):
        await call_anthropic(
            api_key="k",
            model="claude",
            max_tokens=4096,
            system_prompt="sys",
            user_prompt="hi",
        )

    _, kwargs = mock_sdk.AsyncAnthropic.call_args
    assert kwargs.get("timeout") is _ANTHROPIC_TIMEOUT
