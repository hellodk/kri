"""Tests for LLM conversation history (closes #282)."""
import pytest
from fleet_platform.schemas.llm import ChatHistoryMessage, LLMQueryRequest


def test_query_request_accepts_history():
    req = LLMQueryRequest(
        prompt="what are the node names?",
        intent="fleet_query",
        history=[
            ChatHistoryMessage(role="user", content="Hi"),
            ChatHistoryMessage(role="assistant", content="Hello! I can help."),
        ],
    )
    assert len(req.history) == 2
    assert req.history[0].role == "user"


def test_query_request_empty_history_by_default():
    req = LLMQueryRequest(prompt="hello", intent="fleet_query")
    assert req.history == []


def test_history_message_role_must_be_user_or_assistant():
    with pytest.raises(Exception):
        ChatHistoryMessage(role="system", content="not allowed")


def test_openai_compat_includes_history_in_messages(monkeypatch):
    """History entries appear between system and user in the messages list."""
    import asyncio
    import json as _json
    import httpx
    from fleet_platform.services.llm_caller import call_openai_compat

    captured: dict = {}

    async def fake_post(self, url, *, headers, json, **kw):
        captured["messages"] = json["messages"]
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            content=_json.dumps({
                "choices": [{"message": {"content": "hello"}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 10},
            }).encode(),
            headers={"content-type": "application/json"},
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    history = [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello"},
    ]
    asyncio.run(call_openai_compat(
        base_url="http://localhost:11434",
        api_key=None,
        model="llama3",
        max_tokens=256,
        system_prompt="You are a fleet assistant.",
        user_prompt="What are the node names?",
        history=history,
    ))

    roles = [m["role"] for m in captured["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
    assert captured["messages"][-1]["content"] == "What are the node names?"


def test_no_history_produces_system_plus_user(monkeypatch):
    import asyncio
    import json as _json
    import httpx
    from fleet_platform.services.llm_caller import call_openai_compat

    captured: dict = {}

    async def fake_post(self, url, *, headers, json, **kw):
        captured["messages"] = json["messages"]
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            content=_json.dumps({
                "choices": [{"message": {"content": "hi"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }).encode(),
            headers={"content-type": "application/json"},
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    asyncio.run(call_openai_compat(
        base_url="http://localhost:11434",
        api_key=None,
        model="llama3",
        max_tokens=256,
        system_prompt="You are a fleet assistant.",
        user_prompt="Hello",
    ))

    roles = [m["role"] for m in captured["messages"]]
    assert roles == ["system", "user"]
    assert len(captured["messages"]) == 2
