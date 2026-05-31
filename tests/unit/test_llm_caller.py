# tests/unit/test_llm_caller.py
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_call_openai_compat_sends_correct_payload():
    from fleet_platform.services.llm_caller import call_openai_compat

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "# salt state here"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        content, inp, out = await call_openai_compat(
            base_url="http://localhost:11434/v1",
            api_key=None,
            model="llama3.2",
            max_tokens=4096,
            system_prompt="You are helpful.",
            user_prompt="Write a salt state",
        )

    assert content == "# salt state here"
    assert inp == 100
    assert out == 50
    call_args = mock_client.post.call_args
    assert "/chat/completions" in call_args[0][0]


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


def _mock_chat_client():
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "a sufficiently long answer body"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)
    return mock_client


@pytest.mark.asyncio
async def test_call_openai_compat_url_with_trailing_v1():
    """base_url ending in /v1 posts to /v1/chat/completions, not /v1/v1/... (#272)."""
    from fleet_platform.services.llm_caller import call_openai_compat

    mock_client = _mock_chat_client()
    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        await call_openai_compat(
            base_url="http://192.168.1.23:52415/v1",
            api_key=None, model="m", max_tokens=16,
            system_prompt="sys", user_prompt="hi",
        )
    assert mock_client.post.call_args[0][0] == "http://192.168.1.23:52415/v1/chat/completions"


@pytest.mark.asyncio
async def test_call_openai_compat_url_without_v1():
    """A bare base_url (no /v1) resolves to the same /v1/chat/completions endpoint (#272)."""
    from fleet_platform.services.llm_caller import call_openai_compat

    mock_client = _mock_chat_client()
    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        await call_openai_compat(
            base_url="http://192.168.1.23:52415",
            api_key=None, model="m", max_tokens=16,
            system_prompt="sys", user_prompt="hi",
        )
    assert mock_client.post.call_args[0][0] == "http://192.168.1.23:52415/v1/chat/completions"


@pytest.mark.asyncio
async def test_call_openai_compat_groq_preserves_path_prefix():
    """Groq's /openai/v1 prefix survives normalization (#272)."""
    from fleet_platform.services.llm_caller import call_openai_compat

    mock_client = _mock_chat_client()
    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        await call_openai_compat(
            base_url="https://api.groq.com/openai/v1",
            api_key="k", model="m", max_tokens=16,
            system_prompt="sys", user_prompt="hi",
        )
    assert mock_client.post.call_args[0][0] == "https://api.groq.com/openai/v1/chat/completions"


@pytest.mark.asyncio
async def test_call_openai_compat_adds_bearer_header_when_api_key_given():
    from fleet_platform.services.llm_caller import call_openai_compat

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        await call_openai_compat(
            base_url="https://api.openai.com/v1",
            api_key="sk-secret",
            model="gpt-4o",
            max_tokens=4096,
            system_prompt="sys",
            user_prompt="prompt",
        )

    _, kwargs = mock_client.post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer sk-secret"


@pytest.mark.asyncio
async def test_call_openai_compat_no_auth_header_when_no_api_key():
    from fleet_platform.services.llm_caller import call_openai_compat

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2},
    }
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        await call_openai_compat(
            base_url="http://localhost:11434/v1",
            api_key=None,
            model="llama3.2",
            max_tokens=512,
            system_prompt="sys",
            user_prompt="prompt",
        )

    _, kwargs = mock_client.post.call_args
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

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    error_response = MagicMock()
    error_response.status_code = 500
    http_error = httpx.HTTPStatusError("500", request=MagicMock(), response=error_response)
    mock_client.post = AsyncMock(side_effect=http_error)

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
async def test_call_openai_compat_raises_llm_call_error_on_bad_response_shape():
    from fleet_platform.services.llm_caller import LLMCallError, call_openai_compat

    mock_response = MagicMock()
    mock_response.json.return_value = {"choices": []}  # empty choices — IndexError
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("fleet_platform.services.llm_caller.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(LLMCallError, match="Unexpected response shape"):
            await call_openai_compat(
                base_url="http://localhost:11434/v1",
                api_key=None,
                model="llama3.2",
                max_tokens=512,
                system_prompt="sys",
                user_prompt="prompt",
            )
