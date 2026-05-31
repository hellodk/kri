"""Unit tests for model_discovery service (Closes #245)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fleet_platform.services.model_discovery import discover_models


@pytest.mark.asyncio
async def test_discover_ollama_parses_tags():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"models": [{"name": "llama3.2"}, {"name": "mistral"}]}
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client
        result = await discover_models("http://localhost:11434", "ollama")
    assert len(result) == 2
    assert result[0]["id"] == "llama3.2"


@pytest.mark.asyncio
async def test_discover_vllm_parses_openai_format():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": [{"id": "mistral-7b"}, {"id": "llama3-8b"}]}
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client
        result = await discover_models("http://localhost:8000", "vllm")
    assert result[0]["id"] == "mistral-7b"


@pytest.mark.asyncio
async def test_discover_returns_empty_on_connection_error():
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
        mock_client_cls.return_value = mock_client
        result = await discover_models("http://unreachable:9999", "vllm")
    assert result == []


@pytest.mark.asyncio
async def test_discover_llamacpp_same_as_vllm():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": [{"id": "llama-3-8b"}]}
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client
        result = await discover_models("http://localhost:8080", "llamacpp")
    assert result[0]["id"] == "llama-3-8b"


def _mock_openai_models_client():
    """Build a mocked httpx.AsyncClient that returns an OpenAI /v1/models payload."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": [{"id": "exo-model-a"}, {"id": "exo-model-b"}]}
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_resp)
    return mock_client


@pytest.mark.asyncio
async def test_discover_openai_compat_with_trailing_v1_hits_single_v1_models():
    """base_url already ending in /v1 must NOT produce a doubled /v1/v1/models (#272)."""
    mock_client = _mock_openai_models_client()
    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await discover_models("http://192.168.1.23:52415/v1", "openai_compat")
    assert mock_client.get.call_args[0][0] == "http://192.168.1.23:52415/v1/models"
    assert [m["id"] for m in result] == ["exo-model-a", "exo-model-b"]


@pytest.mark.asyncio
async def test_discover_openai_compat_bare_url_hits_v1_models():
    """A bare base_url (no /v1) resolves to the same /v1/models endpoint (#272)."""
    mock_client = _mock_openai_models_client()
    with patch("httpx.AsyncClient", return_value=mock_client):
        await discover_models("http://192.168.1.23:52415", "openai_compat")
    assert mock_client.get.call_args[0][0] == "http://192.168.1.23:52415/v1/models"


@pytest.mark.asyncio
async def test_discover_groq_preserves_provider_path_prefix():
    """Groq's /openai/v1 prefix must survive normalization (#272)."""
    mock_client = _mock_openai_models_client()
    with patch("httpx.AsyncClient", return_value=mock_client):
        await discover_models("https://api.groq.com/openai/v1", "openai_compat")
    assert mock_client.get.call_args[0][0] == "https://api.groq.com/openai/v1/models"
