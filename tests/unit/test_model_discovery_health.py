"""Unit tests for discover_models_with_health and health cache integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from fleet_platform.services.model_discovery import discover_models_with_health
from fleet_platform.services.model_health_cache import clear, get_healthy_models


@pytest.fixture(autouse=True)
def reset_cache():
    clear()
    yield
    clear()


def _make_client(get_resp=None, post_resp=None):
    """Build an AsyncMock httpx client context manager."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    if get_resp is not None:
        mock_client.get = AsyncMock(return_value=get_resp)
    if post_resp is not None:
        mock_client.post = AsyncMock(return_value=post_resp)
    return mock_client


@pytest.mark.asyncio
async def test_ollama_all_healthy_no_latency():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"models": [{"name": "llama3.2"}, {"name": "codestral"}]}
    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value = _make_client(get_resp=mock_resp)
        result = await discover_models_with_health("http://ollama:11434", "ollama", api_key=None)

    assert len(result) == 2
    assert all(m["healthy"] is True for m in result)
    assert all(m["latency_ms"] is None for m in result)


@pytest.mark.asyncio
async def test_ollama_populates_cache():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"models": [{"name": "llama3.2"}]}
    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value = _make_client(get_resp=mock_resp)
        await discover_models_with_health("http://ollama:11434", "ollama", api_key=None)

    healthy = get_healthy_models("http://ollama:11434", "ollama")
    assert len(healthy) == 1
    assert healthy[0]["id"] == "llama3.2"


@pytest.mark.asyncio
async def test_vllm_probes_and_marks_healthy():
    list_resp = MagicMock()
    list_resp.raise_for_status = MagicMock()
    list_resp.json.return_value = {"data": [{"id": "mistral"}]}

    probe_resp = MagicMock()
    probe_resp.raise_for_status = MagicMock()
    probe_resp.json.return_value = {"choices": [{"message": {"content": "hi"}}]}

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=list_resp)
        mock_client.post = AsyncMock(return_value=probe_resp)
        mock_cls.return_value = mock_client
        result = await discover_models_with_health("http://vllm:8000", "vllm", api_key=None)

    assert len(result) == 1
    assert result[0]["healthy"] is True
    assert result[0]["latency_ms"] is not None


@pytest.mark.asyncio
async def test_vllm_marks_unhealthy_on_probe_failure():
    list_resp = MagicMock()
    list_resp.raise_for_status = MagicMock()
    list_resp.json.return_value = {"data": [{"id": "broken"}]}

    probe_resp = MagicMock()
    probe_resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("503", request=MagicMock(), response=MagicMock(status_code=503))
    )

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=list_resp)
        mock_client.post = AsyncMock(return_value=probe_resp)
        mock_cls.return_value = mock_client
        result = await discover_models_with_health("http://vllm:8000", "vllm", api_key=None)

    assert result[0]["healthy"] is False
    assert result[0]["latency_ms"] is None


@pytest.mark.asyncio
async def test_empty_on_unreachable_endpoint():
    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_cls.return_value = mock_client
        result = await discover_models_with_health("http://gone:11434", "ollama", api_key=None)

    assert result == []
