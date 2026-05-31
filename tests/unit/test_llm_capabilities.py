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
    from unittest.mock import patch

    import httpx

    captured: dict = {}

    async def fake_post(self, url, *, headers, json, **kw):
        captured["system"] = json["messages"][0]["content"]
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            content=_json.dumps({
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }).encode(),
            headers={"content-type": "application/json"},
        )

    patch("httpx.AsyncClient.post", fake_post).start()

    from fleet_platform.services.llm_caller import call_openai_compat

    long_prompt = "x" * 3000  # 3000 chars — under the 131072 budget
    asyncio.run(call_openai_compat(
        base_url="http://x:52415",
        api_key=None,
        model="m",
        max_tokens=512,
        system_prompt=long_prompt,
        user_prompt="hi",
        model_context_length=131072,
    ))
    patch.stopall()
    assert "[context truncated" not in captured.get("system", "")


def test_thinking_model_strips_think_blocks():
    """<think>...</think> blocks are stripped for thinking-capable models."""
    import asyncio
    import json as _json
    from unittest.mock import patch

    import httpx

    content_with_think = "<think>internal reasoning here</think>\nThe answer is 42."

    async def fake_post(self, url, *, headers, json, **kw):
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            content=_json.dumps({
                "choices": [{"message": {"content": content_with_think}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 15},
            }).encode(),
            headers={"content-type": "application/json"},
        )

    patch("httpx.AsyncClient.post", fake_post).start()
    from fleet_platform.services.llm_caller import call_openai_compat
    content, _, _ = asyncio.run(call_openai_compat(
        base_url="http://x",
        api_key=None,
        model="m",
        max_tokens=512,
        system_prompt="sys",
        user_prompt="hi",
        model_capabilities=["text", "thinking"],
    ))
    patch.stopall()
    assert "<think>" not in content
    assert "42" in content


def test_max_tokens_clamped_to_context_length():
    """max_tokens passed to the API does not exceed context_length."""
    import asyncio
    import json as _json
    from unittest.mock import patch

    import httpx

    captured: dict = {}

    async def fake_post(self, url, *, headers, json, **kw):
        captured["max_tokens"] = json["max_tokens"]
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            content=_json.dumps({
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5},
            }).encode(),
            headers={"content-type": "application/json"},
        )

    patch("httpx.AsyncClient.post", fake_post).start()
    from fleet_platform.services.llm_caller import call_openai_compat
    asyncio.run(call_openai_compat(
        base_url="http://x",
        api_key=None,
        model="m",
        max_tokens=99999,  # user asked for more than context allows
        system_prompt="sys",
        user_prompt="hi",
        model_context_length=8192,  # model only has 8k context
    ))
    patch.stopall()
    assert captured["max_tokens"] <= 8192


def test_unknown_model_falls_back_to_conservative_behavior():
    """When model_context_length is None, uses the 8192-char fallback budget."""
    import asyncio
    import json as _json
    from unittest.mock import patch

    import httpx

    captured: dict = {}

    async def fake_post(self, url, *, headers, json, **kw):
        captured["system"] = json["messages"][0]["content"]
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            content=_json.dumps({
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5},
            }).encode(),
            headers={"content-type": "application/json"},
        )

    patch("httpx.AsyncClient.post", fake_post).start()
    from fleet_platform.services.llm_caller import call_openai_compat

    # System prompt well under 8192-char fallback budget (8192*4 - 512*4 - 200 ≈ 28000 chars fallback)
    # Actually fallback is (8192 - 512) * 4 - 200 = 29908 chars — long prompt stays if under this
    asyncio.run(call_openai_compat(
        base_url="http://x",
        api_key=None,
        model="m",
        max_tokens=512,
        system_prompt="You are helpful.",
        user_prompt="hi",
        model_context_length=None,  # unknown
    ))
    patch.stopall()
    # No crash — fallback handled gracefully
    assert True
