# tests/unit/test_llm_stream_p1.py
"""Tests for the SSE streaming variant of the LLM caller (P1).

Covers ``stream_openai_compat`` and ``stream_anthropic`` end-to-end at the
service layer — chunk emission, error event shape, and the final ``done``
event with content + token counts. The HTTP route around them is verified
indirectly: any change to the event contract here is a breaking change for
the SSE response builder in ``fleet_platform.api.routes.llm``.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _sse_chunks(parts: list[str], usage: dict | None = None):
    """Mock httpx client whose stream yields one SSE delta per *parts* element."""

    async def _lines():
        for p in parts:
            yield f"data: {json.dumps({'choices': [{'delta': {'content': p}}]})}"
        if usage:
            yield f"data: {json.dumps({'choices': [], 'usage': usage})}"
        yield "data: [DONE]"

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_lines = _lines

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)
    return mock_client


@pytest.mark.asyncio
async def test_stream_openai_compat_emits_deltas_then_done():
    """Each SSE delta becomes a `delta` event; final `done` carries usage."""
    from fleet_platform.services.llm_caller import stream_openai_compat

    mock_client = _sse_chunks(
        ["Hello", " world", "!"],
        usage={"prompt_tokens": 11, "completion_tokens": 3},
    )
    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        events = [
            ev
            async for ev in stream_openai_compat(
                base_url="http://localhost:1234/v1",
                api_key=None,
                model="m",
                max_tokens=64,
                system_prompt="You are helpful.",
                user_prompt="say hi",
            )
        ]

    deltas = [e for e in events if e["type"] == "delta"]
    assert [d["text"] for d in deltas] == ["Hello", " world", "!"]

    done = [e for e in events if e["type"] == "done"]
    assert len(done) == 1
    assert done[0]["content"] == "Hello world!"
    assert done[0]["input_tokens"] == 11
    assert done[0]["output_tokens"] == 3


@pytest.mark.asyncio
async def test_stream_openai_compat_emits_error_event_on_http_failure():
    """A 401/404 from the upstream surfaces as a single `error` event, not an exception."""
    import httpx

    from fleet_platform.services.llm_caller import stream_openai_compat

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "Unauthorized",
            request=MagicMock(),
            response=MagicMock(status_code=401, text="bad key"),
        )
    )

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        events = [
            ev
            async for ev in stream_openai_compat(
                base_url="http://x/v1",
                api_key="k",
                model="m",
                max_tokens=8,
                system_prompt="s",
                user_prompt="u",
            )
        ]

    types = [e["type"] for e in events]
    assert types == ["error"]
    # The error message should describe the upstream context to help operators
    assert "401" in events[0]["error"]


@pytest.mark.asyncio
async def test_stream_openai_compat_thinking_strips_think_blocks():
    """Thinking-model output has <think>…</think> stripped from the final `content`."""
    from fleet_platform.services.llm_caller import stream_openai_compat

    mock_client = _sse_chunks(
        ["<think>", "private reasoning", "</think>", "Final answer"]
    )
    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        events = [
            ev
            async for ev in stream_openai_compat(
                base_url="http://x/v1",
                api_key=None,
                model="m",
                max_tokens=64,
                system_prompt="s",
                user_prompt="u",
                model_capabilities=["thinking"],
            )
        ]

    done = next(e for e in events if e["type"] == "done")
    # The raw deltas still flow through (the UI may want to render the
    # reasoning), but the persisted ``content`` is post-processed.
    assert done["content"] == "Final answer"


@pytest.mark.asyncio
async def test_stream_anthropic_emits_deltas_and_usage():
    """Anthropic stream wrapper produces delta + done events via the SDK adapter."""
    from fleet_platform.services.llm_caller import stream_anthropic

    async def _text_iter() -> AsyncIterator[str]:
        for chunk in ["Hi", " there"]:
            yield chunk

    final_message = MagicMock()
    final_message.usage.input_tokens = 5
    final_message.usage.output_tokens = 2

    stream_ctx = MagicMock()
    stream_ctx.__aenter__ = AsyncMock(
        return_value=MagicMock(
            text_stream=_text_iter(),
            get_final_message=AsyncMock(return_value=final_message),
        )
    )
    stream_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_anthropic_client = MagicMock()
    mock_anthropic_client.messages.stream = MagicMock(return_value=stream_ctx)

    with patch(
        "anthropic.AsyncAnthropic",
        return_value=mock_anthropic_client,
    ):
        events = [
            ev
            async for ev in stream_anthropic(
                api_key="k",
                model="claude-3-5-sonnet",
                max_tokens=64,
                system_prompt="s",
                user_prompt="u",
            )
        ]

    deltas = [e["text"] for e in events if e["type"] == "delta"]
    assert deltas == ["Hi", " there"]
    done = next(e for e in events if e["type"] == "done")
    assert done["content"] == "Hi there"
    assert done["input_tokens"] == 5
    assert done["output_tokens"] == 2
