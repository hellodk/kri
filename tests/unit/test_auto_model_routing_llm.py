"""Unit tests for _resolve_model() in fleet_platform/api/routes/llm.py."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from fleet_platform.api.routes.llm import _resolve_model
from fleet_platform.services import model_health_cache as hc


def _make_endpoint(model: str, provider: str = "ollama", base_url: str = "http://ollama:11434"):
    ep = MagicMock()
    ep.model = model
    ep.provider = provider
    ep.base_url = base_url
    ep.name = "test-endpoint"
    return ep


@pytest.fixture(autouse=True)
def reset_cache():
    hc.clear()
    yield
    hc.clear()


@pytest.mark.asyncio
async def test_non_auto_returns_unchanged():
    ep = _make_endpoint("llama3.2")
    result = await _resolve_model(ep)
    assert result == "llama3.2"


@pytest.mark.asyncio
async def test_auto_returns_lowest_latency_healthy():
    hc.set_health("http://ollama:11434", "ollama", "slow-model", healthy=True, latency_ms=200)
    hc.set_health("http://ollama:11434", "ollama", "fast-model", healthy=True, latency_ms=40)
    hc.set_health("http://ollama:11434", "ollama", "dead-model", healthy=False, latency_ms=None)

    ep = _make_endpoint("__auto__")
    result = await _resolve_model(ep)
    assert result == "fast-model"


@pytest.mark.asyncio
async def test_auto_null_latency_sorts_last():
    hc.set_health("http://ollama:11434", "ollama", "no-latency", healthy=True, latency_ms=None)
    hc.set_health("http://ollama:11434", "ollama", "with-latency", healthy=True, latency_ms=100)

    ep = _make_endpoint("__auto__")
    result = await _resolve_model(ep)
    assert result == "with-latency"


@pytest.mark.asyncio
async def test_auto_stale_cache_reprobes():
    ep = _make_endpoint("__auto__")

    async def _populate(*args, **kwargs):
        hc.set_health("http://ollama:11434", "ollama", "fresh-model", healthy=True, latency_ms=50)

    # All imports inside _resolve_model are dynamic — patch at the source module level
    with (
        patch("fleet_platform.services.model_health_cache.is_stale", return_value=True),
        patch(
            "fleet_platform.services.model_discovery.discover_models_with_health",
            side_effect=_populate,
        ),
        patch("fleet_platform.services.llm_svc.get_decrypted_api_key", return_value=None),
    ):
        result = await _resolve_model(ep)
    assert result == "fresh-model"


@pytest.mark.asyncio
async def test_auto_no_healthy_raises_503():
    hc.set_health("http://ollama:11434", "ollama", "bad-model", healthy=False, latency_ms=None)

    ep = _make_endpoint("__auto__")
    with pytest.raises(HTTPException) as exc_info:
        await _resolve_model(ep)
    assert exc_info.value.status_code == 503
    assert "No healthy models" in exc_info.value.detail
