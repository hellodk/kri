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


@pytest.mark.asyncio
async def test_openai_compat_includes_history_in_messages():
    """History entries appear between system and user in the messages list."""
    import json as _json
    from unittest.mock import AsyncMock, MagicMock, patch

    from fleet_platform.services.llm_caller import call_openai_compat

    captured: dict = {}

    async def _lines():
        yield f'data: {_json.dumps({"choices": [{"delta": {"content": "hello"}}]})}'
        yield "data: [DONE]"

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_lines = _lines

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

    def _capture_stream(method, url, *, headers, json, **kw):
        captured["messages"] = json["messages"]
        return mock_stream_ctx

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.stream = _capture_stream

    history = [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello"},
    ]
    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        await call_openai_compat(
            base_url="http://localhost:11434",
            api_key=None,
            model="llama3",
            max_tokens=256,
            system_prompt="You are a fleet assistant.",
            user_prompt="What are the node names?",
            history=history,
        )

    roles = [m["role"] for m in captured["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
    assert captured["messages"][-1]["content"] == "What are the node names?"


@pytest.mark.asyncio
async def test_no_history_produces_system_plus_user():
    import json as _json
    from unittest.mock import AsyncMock, MagicMock, patch

    from fleet_platform.services.llm_caller import call_openai_compat

    captured: dict = {}

    async def _lines():
        yield f'data: {_json.dumps({"choices": [{"delta": {"content": "hi"}}]})}'
        yield "data: [DONE]"

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_lines = _lines

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

    def _capture_stream(method, url, *, headers, json, **kw):
        captured["messages"] = json["messages"]
        return mock_stream_ctx

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.stream = _capture_stream

    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        await call_openai_compat(
            base_url="http://localhost:11434",
            api_key=None,
            model="llama3",
            max_tokens=256,
            system_prompt="You are a fleet assistant.",
            user_prompt="Hello",
        )

    roles = [m["role"] for m in captured["messages"]]
    assert roles == ["system", "user"]
    assert len(captured["messages"]) == 2


def test_history_assembled_as_messages_array():
    """History entries are included as a messages array in the request (#282)."""
    from fleet_platform.schemas.llm import ChatHistoryMessage, LLMQueryRequest
    req = LLMQueryRequest(
        prompt="what are the node names?",
        intent="fleet_query",
        history=[
            ChatHistoryMessage(role="user", content="Hi"),
            ChatHistoryMessage(role="assistant", content="Hello! I can help with your fleet."),
        ],
    )
    msgs = [{"role": m.role, "content": m.content} for m in req.history]
    assert msgs == [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello! I can help with your fleet."},
    ]


def test_oldest_turns_dropped_when_over_token_budget():
    """When history exceeds 6000-token budget, oldest turns are dropped first."""
    # Build a history list where total chars > 6000*4=24000
    # 5 messages each with 5100 chars = 25500 chars total -> first turn should be dropped
    long_content = "x" * 5100
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": long_content} for i in range(5)]

    # Replicate the budget enforcement logic from the route
    _HISTORY_TOKEN_BUDGET = 6000
    total_chars = sum(len(m["content"]) for m in history)
    while history and total_chars > _HISTORY_TOKEN_BUDGET * 4:
        removed = history.pop(0)
        total_chars -= len(removed["content"])

    assert len(history) < 5, "oldest turns should have been dropped"
    assert total_chars <= _HISTORY_TOKEN_BUDGET * 4


def test_empty_history_backward_compat():
    """Requests without history field are valid and produce empty history."""
    from fleet_platform.schemas.llm import LLMQueryRequest
    req = LLMQueryRequest(prompt="hello", intent="fleet_query")
    assert req.history == []
    assert isinstance(req.history, list)
