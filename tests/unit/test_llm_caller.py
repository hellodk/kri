# tests/unit/test_llm_caller.py
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_call_openai_compat_sends_correct_payload():
    from fleet_platform.services.llm_caller import call_openai_compat

    mock_client = _sse_from_text("# salt state here")
    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        content, _inp, _out = await call_openai_compat(
            base_url="http://localhost:11434/v1",
            api_key=None,
            model="llama3.2",
            max_tokens=4096,
            system_prompt="You are helpful.",
            user_prompt="Write a salt state",
        )

    assert content == "# salt state here"
    assert "/chat/completions" in mock_client.stream.call_args[0][1]


def test_normalize_openai_base_url_strips_trailing_v1_and_slashes():
    from fleet_platform.services.llm_caller import normalize_openai_base_url

    assert normalize_openai_base_url("http://x:52415/v1") == "http://x:52415"
    assert normalize_openai_base_url("http://x:52415/v1/") == "http://x:52415"
    assert normalize_openai_base_url("http://x:52415/") == "http://x:52415"
    assert normalize_openai_base_url("http://x:52415") == "http://x:52415"
    # Provider path prefixes (Groq) are preserved; only a trailing /v1 is stripped
    assert normalize_openai_base_url("https://api.groq.com/openai/v1") == "https://api.groq.com/openai"
    # Idempotent
    once = normalize_openai_base_url("http://x:52415/v1")
    assert normalize_openai_base_url(once) == once


def _sse_from_text(text: str):
    """Build a streaming mock that yields SSE lines for *text*."""
    import json as _json

    async def _lines():
        yield f"data: {_json.dumps({'choices': [{'delta': {'content': text}}]})}"
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


def _mock_chat_client():
    return _sse_from_text("a sufficiently long answer body")


@pytest.mark.asyncio
async def test_call_openai_compat_url_with_trailing_v1():
    """base_url ending in /v1 posts to /v1/chat/completions, not /v1/v1/... (#272)."""
    from fleet_platform.services.llm_caller import call_openai_compat

    mock_client = _mock_chat_client()
    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        await call_openai_compat(
            base_url="http://192.168.1.23:52415/v1",
            api_key=None,
            model="m",
            max_tokens=16,
            system_prompt="sys",
            user_prompt="hi",
        )
    assert mock_client.stream.call_args[0][1] == "http://192.168.1.23:52415/v1/chat/completions"


@pytest.mark.asyncio
async def test_call_openai_compat_url_without_v1():
    """A bare base_url (no /v1) resolves to the same /v1/chat/completions endpoint (#272)."""
    from fleet_platform.services.llm_caller import call_openai_compat

    mock_client = _mock_chat_client()
    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        await call_openai_compat(
            base_url="http://192.168.1.23:52415",
            api_key=None,
            model="m",
            max_tokens=16,
            system_prompt="sys",
            user_prompt="hi",
        )
    assert mock_client.stream.call_args[0][1] == "http://192.168.1.23:52415/v1/chat/completions"


@pytest.mark.asyncio
async def test_call_openai_compat_groq_preserves_path_prefix():
    """Groq's /openai/v1 prefix survives normalization (#272)."""
    from fleet_platform.services.llm_caller import call_openai_compat

    mock_client = _mock_chat_client()
    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        await call_openai_compat(
            base_url="https://api.groq.com/openai/v1",
            api_key="k",
            model="m",
            max_tokens=16,
            system_prompt="sys",
            user_prompt="hi",
        )
    assert mock_client.stream.call_args[0][1] == "https://api.groq.com/openai/v1/chat/completions"


@pytest.mark.asyncio
async def test_call_openai_compat_adds_bearer_header_when_api_key_given():
    from fleet_platform.services.llm_caller import call_openai_compat

    mock_client = _sse_from_text("ok")
    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        await call_openai_compat(
            base_url="https://api.openai.com/v1",
            api_key="sk-secret",
            model="gpt-4o",
            max_tokens=4096,
            system_prompt="sys",
            user_prompt="prompt",
        )

    _, kwargs = mock_client.stream.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer sk-secret"


@pytest.mark.asyncio
async def test_call_openai_compat_no_auth_header_when_no_api_key():
    from fleet_platform.services.llm_caller import call_openai_compat

    mock_client = _sse_from_text("ok")
    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        await call_openai_compat(
            base_url="http://localhost:11434/v1",
            api_key=None,
            model="llama3.2",
            max_tokens=512,
            system_prompt="sys",
            user_prompt="prompt",
        )

    _, kwargs = mock_client.stream.call_args
    assert "Authorization" not in kwargs["headers"]


@pytest.mark.asyncio
async def test_call_anthropic_sends_correct_structure():
    from fleet_platform.services.llm_caller import call_anthropic

    mock_sdk = MagicMock()
    mock_client_instance = AsyncMock()
    mock_sdk.AsyncAnthropic.return_value = mock_client_instance

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="- the playbook")]
    mock_message.usage.input_tokens = 200
    mock_message.usage.output_tokens = 80
    mock_client_instance.messages.create = AsyncMock(return_value=mock_message)

    with patch.dict("sys.modules", {"anthropic": mock_sdk}):
        content, inp, out = await call_anthropic(
            api_key="ant-key",
            model="claude-opus-4-7",
            max_tokens=4096,
            system_prompt="sys",
            user_prompt="write a playbook",
        )

    assert content == "- the playbook"
    assert inp == 200
    assert out == 80


@pytest.mark.asyncio
async def test_call_openai_compat_raises_llm_call_error_on_http_error():
    import httpx

    from fleet_platform.services.llm_caller import LLMCallError, call_openai_compat

    error_response = MagicMock()
    error_response.status_code = 500
    http_error = httpx.HTTPStatusError("500", request=MagicMock(), response=error_response)

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(side_effect=http_error)
    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(LLMCallError, match="HTTP 500"):
            await call_openai_compat(
                base_url="http://localhost:11434/v1",
                api_key=None,
                model="llama3.2",
                max_tokens=512,
                system_prompt="sys",
                user_prompt="prompt",
            )


@pytest.mark.asyncio
async def test_call_openai_compat_raises_on_no_content_deltas():
    """A stream with no content deltas and 0 completion tokens raises LLMCallError (#840).

    Previously returned a placeholder string; now raises so the endpoint is
    marked unhealthy rather than silently accepted as a successful response.
    """
    from fleet_platform.services.llm_caller import LLMCallError, call_openai_compat

    # Override the aiter_lines to yield only [DONE] — no content, no usage
    async def _done_only():
        yield "data: [DONE]"

    mock_client = _sse_from_text("")
    mock_client.stream.return_value.__aenter__.return_value.aiter_lines = _done_only

    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(LLMCallError, match="0 tokens"):
            await call_openai_compat(
                base_url="http://localhost:11434/v1",
                api_key=None,
                model="llama3.2",
                max_tokens=512,
                system_prompt="sys",
                user_prompt="prompt",
            )


def test_validate_response_returns_error_for_empty_content():
    """Too-short content (< 5 chars) returns a helpful error message."""
    from fleet_platform.services.llm_caller import _validate_response

    result = _validate_response("hi", "You are a fleet assistant.")
    assert result.startswith("[")
    assert "empty" in result.lower() or "model" in result.lower()


def test_validate_response_detects_system_prompt_echo():
    """Content that echoes the system prompt is flagged as garbled."""
    from fleet_platform.services.llm_caller import _validate_response

    sys_prompt = "You are an AI assistant embedded in kri fleet management."
    garbled = sys_prompt + " you are a user you are a user"
    result = _validate_response(garbled, sys_prompt)
    assert result.startswith("[")
    assert "echoed" in result.lower() or "model" in result.lower()


def test_validate_response_strips_chat_template_artifacts():
    """Chat template tokens are stripped; good content underneath is returned."""
    from fleet_platform.services.llm_caller import _validate_response

    content = "<|im_start|>assistant\nHere is the salt state you need.<|im_end|>"
    result = _validate_response(content, "You are helpful.")
    assert "<|im_start|>" not in result
    assert "salt state" in result


def test_validate_response_returns_error_when_only_artifacts():
    """Content consisting only of chat template tokens gets an error message."""
    from fleet_platform.services.llm_caller import _validate_response

    result = _validate_response("<|im_start|><|im_end|>", "System prompt here.")
    assert result.startswith("[")


def test_validate_response_passes_clean_content_through():
    """Normal, useful content is returned unchanged."""
    from fleet_platform.services.llm_caller import _validate_response

    content = "The SaltStack state file for restarting nginx is:\n```sls\nnginx:\n  service.running\n```"
    result = _validate_response(content, "You are an assistant.")
    assert result == content


# ── #274 Streaming tests ──────────────────────────────────────────────────────


def _sse_lines(*chunks, usage=None):
    """Yield fake SSE lines for the given content chunks."""

    async def _gen():
        for text in chunks:
            yield f"data: {json.dumps({'choices': [{'delta': {'content': text}}]})}"
        if usage:
            yield f"data: {json.dumps({'choices': [], 'usage': usage})}"
        yield "data: [DONE]"

    return _gen()


@pytest.mark.asyncio
async def test_stream_aggregates_deltas_into_full_content():
    """SSE delta chunks are aggregated into the final content string (#274)."""
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_lines = lambda: _sse_lines("Hello", " world", "!")

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    from fleet_platform.services.llm_caller import call_openai_compat

    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        content, inp, out = await call_openai_compat(
            base_url="http://x",
            api_key=None,
            model="m",
            max_tokens=128,
            system_prompt="sys",
            user_prompt="hi",
        )

    assert content == "Hello world!"


@pytest.mark.asyncio
async def test_stream_read_timeout_raises_llm_call_error():
    """A stalled stream (no chunks) raises LLMCallError with a useful message (#274)."""
    from unittest.mock import AsyncMock, MagicMock, patch

    import httpx as _httpx

    from fleet_platform.services.llm_caller import LLMCallError, call_openai_compat

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    async def stalled_lines():
        raise _httpx.ReadTimeout("stalled", request=MagicMock())
        yield  # make it an async generator

    mock_response.aiter_lines = stalled_lines

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(LLMCallError, match="stalled|overloaded"):
            await call_openai_compat(
                base_url="http://x",
                api_key=None,
                model="m",
                max_tokens=128,
                system_prompt="sys",
                user_prompt="hi",
            )


@pytest.mark.asyncio
async def test_stream_empty_response_raises_llm_call_error():
    """An empty stream (no content, 0 completion tokens) raises LLMCallError (#840).

    Previously returned a placeholder; now raises so callers can mark the
    endpoint unhealthy instead of silently accepting a broken response.
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    from fleet_platform.services.llm_caller import LLMCallError, call_openai_compat

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    async def empty_stream():
        yield "data: [DONE]"

    mock_response.aiter_lines = empty_stream

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(LLMCallError, match="0 tokens"):
            await call_openai_compat(
                base_url="http://x",
                api_key=None,
                model="m",
                max_tokens=128,
                system_prompt="sys",
                user_prompt="hi",
            )


# ─── streaming edge cases (#309) ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_skips_malformed_json_midstream_and_continues():
    """A bad JSON chunk must be silently skipped; aggregation continues."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from fleet_platform.services.llm_caller import call_openai_compat

    async def _lines_with_bad_chunk():
        yield f"data: {json.dumps({'choices': [{'delta': {'content': 'Hello'}}]})}"
        yield "data: {this is not valid json!!!"
        yield f"data: {json.dumps({'choices': [{'delta': {'content': ' world'}}]})}"
        yield "data: [DONE]"

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_lines = _lines_with_bad_chunk

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        content, _inp, _out = await call_openai_compat(
            base_url="http://x",
            api_key=None,
            model="m",
            max_tokens=128,
            system_prompt="sys",
            user_prompt="hi",
        )

    assert content == "Hello world"


@pytest.mark.asyncio
async def test_stream_parses_usage_tokens_from_final_chunk():
    """Token counts must be extracted from the usage chunk, not left at 0."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from fleet_platform.services.llm_caller import call_openai_compat

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_lines = lambda: _sse_lines(
        "The answer is 42",
        usage={"prompt_tokens": 123, "completion_tokens": 45},
    )

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        content, inp, out = await call_openai_compat(
            base_url="http://x",
            api_key=None,
            model="m",
            max_tokens=128,
            system_prompt="sys",
            user_prompt="hi",
        )

    assert inp == 123
    assert out == 45
    assert "42" in content


@pytest.mark.asyncio
async def test_stream_usage_missing_defaults_to_zero():
    """If provider sends no usage chunk, tokens must be (content, 0, 0)."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from fleet_platform.services.llm_caller import call_openai_compat

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_lines = lambda: _sse_lines("some content")  # no usage kwarg

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        _content, inp, out = await call_openai_compat(
            base_url="http://x",
            api_key=None,
            model="m",
            max_tokens=128,
            system_prompt="sys",
            user_prompt="hi",
        )

    assert inp == 0
    assert out == 0


@pytest.mark.asyncio
async def test_thinking_model_strips_think_blocks():
    """Thinking models: <think>...</think> blocks must be stripped from output."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from fleet_platform.services.llm_caller import call_openai_compat

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_lines = lambda: _sse_lines("<think>reasoning here</think>Final answer")

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        content, _inp, _out = await call_openai_compat(
            base_url="http://x",
            api_key=None,
            model="m",
            max_tokens=128,
            system_prompt="sys",
            user_prompt="hi",
            model_capabilities=["thinking"],
        )

    assert content == "Final answer"
    assert "<think>" not in content


@pytest.mark.asyncio
async def test_max_tokens_clamped_to_model_context_length():
    """max_tokens must be clamped to model_context_length when it would exceed it."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from fleet_platform.services.llm_caller import call_openai_compat

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_lines = lambda: _sse_lines("ok")

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        await call_openai_compat(
            base_url="http://x",
            api_key=None,
            model="m",
            max_tokens=99999,
            system_prompt="sys",
            user_prompt="hi",
            model_context_length=4096,
        )

    kwargs = mock_client.stream.call_args[1]
    sent_payload = kwargs["json"]
    assert sent_payload["max_tokens"] <= 4096
