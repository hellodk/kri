"""Tests for #840 — empty-stream / 0-token response marks endpoint unhealthy.

Covers:
- call_openai_compat: empty stream with 0 completion tokens → LLMCallError
- call_openai_compat: non-empty response is NOT treated as failure
- stream_openai_compat: empty stream with 0 completion tokens → error event
- call_anthropic: 0 output tokens → LLMCallError
- stream_anthropic: 0 output tokens → error event
- _probe_model: 200 with empty completion → (False, None)
- _probe_model: 200 with assistant content → (True, latency)
- _probe_model: 200 with completion_tokens >= 1 → (True, latency)
- _probe_model: timeout/connect error → (None, None)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from fleet_platform.services.llm_caller import LLMCallError

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_sse_stream(lines: list[str]):
    """Build a streaming mock that yields the given SSE lines."""

    async def _aiter():
        for line in lines:
            yield line

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_lines = _aiter

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)
    return mock_client


def _make_probe_response(body: dict):
    """Return a mock httpx Response that raises_for_status cleanly and returns body."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=body)
    return resp


# ── call_openai_compat ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_call_openai_compat_empty_stream_raises_llm_call_error():
    """Empty stream with 0 completion tokens must raise LLMCallError, not return a placeholder."""
    from fleet_platform.services.llm_caller import call_openai_compat

    # Only [DONE] — no content deltas, no usage chunk
    mock_client = _make_sse_stream(["data: [DONE]"])

    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(LLMCallError, match="0 tokens"):
            await call_openai_compat(
                base_url="http://mlx:8080",
                api_key=None,
                model="mlx-community/Qwen3-4B",
                max_tokens=512,
                system_prompt="sys",
                user_prompt="hello",
            )


@pytest.mark.asyncio
async def test_call_openai_compat_nonempty_response_succeeds():
    """A normal non-empty response must still succeed."""
    from fleet_platform.services.llm_caller import call_openai_compat

    usage_chunk = json.dumps({"usage": {"prompt_tokens": 10, "completion_tokens": 5}})
    mock_client = _make_sse_stream(
        [
            f"data: {json.dumps({'choices': [{'delta': {'content': 'Hello!'}}]})}",
            f"data: {usage_chunk}",
            "data: [DONE]",
        ]
    )

    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        content, inp, out = await call_openai_compat(
            base_url="http://mlx:8080",
            api_key=None,
            model="mlx-community/Qwen3-4B",
            max_tokens=512,
            system_prompt="sys",
            user_prompt="hello",
        )
    assert content == "Hello!"
    assert inp == 10
    assert out == 5


@pytest.mark.asyncio
async def test_call_openai_compat_content_without_usage_chunk_succeeds():
    """Content present but no usage chunk (completion_tokens stays 0) must NOT fail.

    The empty-response check is ONLY triggered when content is also empty.
    """
    from fleet_platform.services.llm_caller import call_openai_compat

    mock_client = _make_sse_stream(
        [
            f"data: {json.dumps({'choices': [{'delta': {'content': 'short'}}]})}",
            "data: [DONE]",
        ]
    )

    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        content, _, out = await call_openai_compat(
            base_url="http://mlx:8080",
            api_key=None,
            model="mlx-community/Qwen3-4B",
            max_tokens=512,
            system_prompt="sys",
            user_prompt="hello",
        )
    assert content == "short"
    # #1048: usage missing -> estimated from content length (non-zero)
    assert out > 0


# ── stream_openai_compat ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_openai_compat_empty_stream_yields_error_event():
    """Empty stream with 0 completion tokens must yield an error event."""
    from fleet_platform.services.llm_caller import stream_openai_compat

    mock_client = _make_sse_stream(["data: [DONE]"])

    events = []
    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        async for event in stream_openai_compat(
            base_url="http://mlx:8080",
            api_key=None,
            model="mlx-community/Qwen3-4B",
            max_tokens=512,
            system_prompt="sys",
            user_prompt="hello",
        ):
            events.append(event)

    assert any(e.get("type") == "error" for e in events), f"Expected error event, got {events}"
    error_event = next(e for e in events if e.get("type") == "error")
    assert "0 tokens" in error_event["error"]
    # Must NOT emit a done event after an error
    assert not any(e.get("type") == "done" for e in events)


@pytest.mark.asyncio
async def test_stream_openai_compat_nonempty_yields_done():
    """A normal non-empty stream must yield delta + done events."""
    from fleet_platform.services.llm_caller import stream_openai_compat

    usage_chunk = json.dumps({"usage": {"prompt_tokens": 8, "completion_tokens": 3}})
    answer = "Hello, fleet operator!"
    mock_client = _make_sse_stream(
        [
            f"data: {json.dumps({'choices': [{'delta': {'content': answer}}]})}",
            f"data: {usage_chunk}",
            "data: [DONE]",
        ]
    )

    events = []
    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        async for event in stream_openai_compat(
            base_url="http://mlx:8080",
            api_key=None,
            model="mlx-community/Qwen3-4B",
            max_tokens=512,
            system_prompt="sys",
            user_prompt="hello",
        ):
            events.append(event)

    assert any(e.get("type") == "delta" for e in events)
    done = next((e for e in events if e.get("type") == "done"), None)
    assert done is not None
    assert done["content"] == answer


# ── call_anthropic ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_call_anthropic_zero_output_tokens_raises_llm_call_error():
    """Anthropic response with 0 output tokens and no content must raise LLMCallError."""
    import anthropic as _anthropic

    from fleet_platform.services.llm_caller import call_anthropic

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="")]
    mock_message.usage.input_tokens = 10
    mock_message.usage.output_tokens = 0

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_message)

    with patch.object(_anthropic, "AsyncAnthropic", return_value=mock_client):
        with pytest.raises(LLMCallError, match="0 tokens"):
            await call_anthropic(
                api_key="sk-test",
                model="claude-3-haiku-20240307",
                max_tokens=256,
                system_prompt="sys",
                user_prompt="hello",
            )


# ── stream_anthropic ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_anthropic_zero_output_tokens_yields_error_event():
    """Anthropic stream with 0 output tokens and no content must yield an error event."""
    import anthropic as _anthropic

    from fleet_platform.services.llm_caller import stream_anthropic

    mock_final = MagicMock()
    mock_final.usage.input_tokens = 10
    mock_final.usage.output_tokens = 0

    async def _empty_text_stream():
        return
        yield  # makes it an async generator

    mock_stream_cm = MagicMock()
    mock_stream_cm.__aenter__ = AsyncMock(return_value=mock_stream_cm)
    mock_stream_cm.__aexit__ = AsyncMock(return_value=None)
    mock_stream_cm.text_stream = _empty_text_stream()
    mock_stream_cm.get_final_message = AsyncMock(return_value=mock_final)

    mock_client = AsyncMock()
    mock_client.messages.stream = MagicMock(return_value=mock_stream_cm)

    events = []
    with patch.object(_anthropic, "AsyncAnthropic", return_value=mock_client):
        async for event in stream_anthropic(
            api_key="sk-test",
            model="claude-3-haiku-20240307",
            max_tokens=256,
            system_prompt="sys",
            user_prompt="hello",
        ):
            events.append(event)

    assert any(e.get("type") == "error" for e in events), f"Expected error event, got {events}"
    error_event = next(e for e in events if e.get("type") == "error")
    assert "0 tokens" in error_event["error"]
    assert not any(e.get("type") == "done" for e in events)


# ── _probe_model ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_probe_model_empty_completion_returns_false():
    """A 200 probe response with empty content and 0 completion_tokens must return (False, None).

    This is the vllm-mlx crash scenario: server returns 200 but delivers nothing.
    """
    from fleet_platform.services.model_discovery import _probe_model

    probe_resp = _make_probe_response(
        {
            "choices": [{"message": {"content": ""}}],
            "usage": {"completion_tokens": 0, "prompt_tokens": 5},
        }
    )

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=probe_resp)
        mock_cls.return_value = mock_client

        healthy, latency = await _probe_model("http://mlx:8080", "model-x", api_key=None)

    assert healthy is False, "Empty completion must be definitively unhealthy"
    assert latency is None


@pytest.mark.asyncio
async def test_probe_model_empty_body_returns_false():
    """A 200 probe with completely empty body (no choices, no usage) must return (False, None)."""
    from fleet_platform.services.model_discovery import _probe_model

    probe_resp = _make_probe_response({})

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=probe_resp)
        mock_cls.return_value = mock_client

        healthy, latency = await _probe_model("http://mlx:8080", "model-x", api_key=None)

    assert healthy is False


@pytest.mark.asyncio
async def test_probe_model_with_assistant_content_returns_true():
    """A 200 probe with non-empty assistant message content must return (True, latency)."""
    from fleet_platform.services.model_discovery import _probe_model

    probe_resp = _make_probe_response(
        {
            "choices": [{"message": {"content": "hi"}}],
            "usage": {"completion_tokens": 1, "prompt_tokens": 5},
        }
    )

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=probe_resp)
        mock_cls.return_value = mock_client

        healthy, latency = await _probe_model("http://mlx:8080", "model-x", api_key=None)

    assert healthy is True
    assert latency is not None and latency >= 0


@pytest.mark.asyncio
async def test_probe_model_with_completion_tokens_only_returns_true():
    """A 200 probe with completion_tokens >= 1 (even without content) must return (True, latency)."""
    from fleet_platform.services.model_discovery import _probe_model

    probe_resp = _make_probe_response(
        {
            "choices": [{"message": {"content": ""}}],
            "usage": {"completion_tokens": 1, "prompt_tokens": 5},
        }
    )

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=probe_resp)
        mock_cls.return_value = mock_client

        healthy, latency = await _probe_model("http://mlx:8080", "model-x", api_key=None)

    assert healthy is True
    assert latency is not None


@pytest.mark.asyncio
async def test_probe_model_timeout_returns_none():
    """A timeout during probe must return (None, None) — server is busy, not broken."""
    from fleet_platform.services.model_discovery import _probe_model

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        mock_cls.return_value = mock_client

        healthy, latency = await _probe_model("http://mlx:8080", "model-x", api_key=None)

    assert healthy is None
    assert latency is None


@pytest.mark.asyncio
async def test_probe_model_http_error_returns_false():
    """A definitive HTTP error (5xx) must still return (False, None)."""
    from fleet_platform.services.model_discovery import _probe_model

    probe_resp = MagicMock()
    probe_resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "500 Internal Server Error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )
    )

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=probe_resp)
        mock_cls.return_value = mock_client

        healthy, latency = await _probe_model("http://mlx:8080", "model-x", api_key=None)

    assert healthy is False
    assert latency is None
