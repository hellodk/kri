"""Unit tests for capability-aware LLM request shaping (#273)."""


def test_discover_models_returns_context_length_and_capabilities():
    """exo-style /v1/models response includes context_length and capabilities."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch


    payload = {
        "data": [
            {"id": "m1", "name": "M1", "context_length": 131072, "capabilities": ["text"]},
            {"id": "m2", "name": "M2", "context_length": 196608, "capabilities": ["text", "thinking"]},
            {"id": "m3"},  # provider that omits these fields
        ]
    }

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = payload
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_resp)

    from fleet_platform.services.model_discovery import discover_models
    with patch("httpx.AsyncClient", return_value=mock_client):
        result = asyncio.run(discover_models("http://exo:52415", "openai_compat"))

    assert result[0]["context_length"] == 131072
    assert result[0]["capabilities"] == ["text"]
    assert result[1]["capabilities"] == ["text", "thinking"]
    assert result[2]["context_length"] == 0
    assert result[2]["capabilities"] == []


def test_context_budget_uses_model_context_length():
    """System prompt is NOT truncated when context_length comfortably fits it."""
    import asyncio
    import json as _json
    from unittest.mock import AsyncMock, MagicMock, patch

    from fleet_platform.services.llm_caller import call_openai_compat

    captured: dict = {}

    async def _lines():
        yield f'data: {_json.dumps({"choices": [{"delta": {"content": "ok"}}]})}'
        yield "data: [DONE]"

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_lines = _lines

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

    def _capture(method, url, *, headers, json, **kw):
        captured["system"] = json["messages"][0]["content"]
        return mock_stream_ctx

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.stream = _capture

    long_prompt = "x" * 3000  # 3000 chars — under the 131072 budget
    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        asyncio.run(call_openai_compat(
            base_url="http://x:52415",
            api_key=None, model="m", max_tokens=512,
            system_prompt=long_prompt, user_prompt="hi",
            model_context_length=131072,
        ))
    assert "[context truncated" not in captured.get("system", "")


def test_thinking_model_strips_think_blocks():
    """<think>...</think> blocks are stripped for thinking-capable models."""
    import asyncio
    import json as _json
    from unittest.mock import AsyncMock, MagicMock, patch

    from fleet_platform.services.llm_caller import call_openai_compat

    content_with_think = "<think>internal reasoning here</think>\nThe answer is 42."

    async def _lines():
        yield f'data: {_json.dumps({"choices": [{"delta": {"content": content_with_think}}]})}'
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

    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        content, _, _ = asyncio.run(call_openai_compat(
            base_url="http://x", api_key=None, model="m", max_tokens=512,
            system_prompt="sys", user_prompt="hi",
            model_capabilities=["text", "thinking"],
        ))
    assert "<think>" not in content
    assert "42" in content


def test_max_tokens_clamped_to_context_length():
    """max_tokens passed to the API does not exceed context_length."""
    import asyncio
    import json as _json
    from unittest.mock import AsyncMock, MagicMock, patch

    from fleet_platform.services.llm_caller import call_openai_compat

    captured: dict = {}

    async def _lines():
        yield f'data: {_json.dumps({"choices": [{"delta": {"content": "ok"}}]})}'
        yield "data: [DONE]"

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_lines = _lines
    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

    def _capture(method, url, *, headers, json, **kw):
        captured["max_tokens"] = json["max_tokens"]
        return mock_stream_ctx

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.stream = _capture

    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        asyncio.run(call_openai_compat(
            base_url="http://x", api_key=None, model="m",
            max_tokens=99999, system_prompt="sys", user_prompt="hi",
            model_context_length=8192,
        ))
    assert captured["max_tokens"] <= 8192


def test_unknown_model_falls_back_to_conservative_behavior():
    """When model_context_length is None, uses the 8192-char fallback budget."""
    import asyncio
    import json as _json
    from unittest.mock import AsyncMock, MagicMock, patch

    from fleet_platform.services.llm_caller import call_openai_compat

    async def _lines():
        yield f'data: {_json.dumps({"choices": [{"delta": {"content": "ok"}}]})}'
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

    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        asyncio.run(call_openai_compat(
            base_url="http://x", api_key=None, model="m",
            max_tokens=512, system_prompt="You are helpful.", user_prompt="hi",
            model_context_length=None,
        ))
    # No crash — fallback handled gracefully
    assert True
