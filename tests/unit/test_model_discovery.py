"""Unit tests for model_discovery service (Closes #245)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
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
