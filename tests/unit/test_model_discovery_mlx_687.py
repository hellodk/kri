"""Tests for #687 — MLX-LM models greyed out as unreachable.

Root causes:
1. Probe timeout was too short (5s) for MLX cold-load.
2. Concurrent probes caused reload thrash on single-model-serving backends.
3. Frontend gated selection on healthy flag.

Design decisions under test:
- A probe timeout/connect error (not an HTTP error) must NOT mark a listed model unhealthy.
- A definitive HTTP error (4xx/5xx) MUST mark the model unhealthy.
- Probes must run sequentially (not concurrently via asyncio.gather).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from fleet_platform.services.model_discovery import discover_models_with_health
from fleet_platform.services.model_health_cache import clear


@pytest.fixture(autouse=True)
def reset_cache():
    clear()
    yield
    clear()


def _make_list_response(model_ids: list[str]) -> MagicMock:
    """Return a mock GET /v1/models response listing the given model IDs."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"data": [{"id": mid} for mid in model_ids]}
    return resp


@pytest.mark.asyncio
async def test_listed_model_stays_selectable_on_probe_timeout():
    """A timeout during probing must NOT mark the listed model unhealthy.

    MLX loads models on-demand; the first probe often times out because
    the model is still being loaded. The model definitely exists (it was
    listed by /v1/models), so it must remain selectable.
    """
    list_resp = _make_list_response(["Qwen3.5-4B"])

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=list_resp)
        # Probe POST raises a timeout — server is busy loading the model
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        mock_cls.return_value = mock_client

        result = await discover_models_with_health("http://mlx:8080", "mlx_lm", api_key=None)

    assert len(result) == 1
    model = result[0]
    assert model["id"] == "Qwen3.5-4B"
    # CRITICAL: timeout must NOT mark the model unhealthy — it must stay selectable
    assert model["healthy"] is True, (
        "A probe timeout must not gate selection — the model is listed and the server is just busy loading it."
    )
    assert model["latency_ms"] is None


@pytest.mark.asyncio
async def test_listed_model_stays_selectable_on_connect_error():
    """A connection error during probing also must not mark the model unhealthy.

    Same principle as timeout: the model was listed, so it exists.
    """
    list_resp = _make_list_response(["Qwen3.5-4B"])

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=list_resp)
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
        mock_cls.return_value = mock_client

        result = await discover_models_with_health("http://mlx:8080", "mlx_lm", api_key=None)

    assert len(result) == 1
    assert result[0]["healthy"] is True


@pytest.mark.asyncio
async def test_listed_model_unhealthy_on_http_error():
    """A definitive HTTP error (4xx/5xx) from the probe MUST mark the model unhealthy.

    This is different from a timeout/connect error: the server responded with a
    clear error status, meaning the model is genuinely broken.
    """
    list_resp = _make_list_response(["broken-model"])

    probe_resp = MagicMock()
    probe_resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "503 Service Unavailable",
            request=MagicMock(),
            response=MagicMock(status_code=503),
        )
    )

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=list_resp)
        mock_client.post = AsyncMock(return_value=probe_resp)
        mock_cls.return_value = mock_client

        result = await discover_models_with_health("http://mlx:8080", "mlx_lm", api_key=None)

    assert len(result) == 1
    assert result[0]["healthy"] is False, "A definitive HTTP error must mark the model unhealthy."
    assert result[0]["latency_ms"] is None


@pytest.mark.asyncio
async def test_probes_run_sequentially():
    """Probes must run one at a time, not concurrently.

    MLX serves ONE model at a time. Concurrent probes for different models
    force model reload thrash, causing every probe to time out. Sequential
    probing avoids this.
    """
    list_resp = _make_list_response(["model-a", "model-b", "model-c"])

    probe_resp = MagicMock()
    probe_resp.raise_for_status = MagicMock()
    probe_resp.json.return_value = {"choices": [{"message": {"content": "hi"}}]}

    with patch("fleet_platform.services.model_discovery._probe_model") as mock_probe:
        # Each call returns (True, 42) — healthy with 42ms latency
        mock_probe = AsyncMock(return_value=(True, 42))
        with patch("fleet_platform.services.model_discovery._probe_model", mock_probe):
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client.get = AsyncMock(return_value=list_resp)
                mock_cls.return_value = mock_client

                result = await discover_models_with_health("http://mlx:8080", "mlx_lm", api_key=None)

    # All 3 models must be probed
    assert mock_probe.await_count == 3, f"Expected _probe_model to be called 3 times, got {mock_probe.await_count}"
    # Calls must be in model order (sequential, not concurrent)
    expected_ids = ["model-a", "model-b", "model-c"]
    actual_ids = [c.args[1] for c in mock_probe.call_args_list]
    assert actual_ids == expected_ids, f"Expected sequential calls for {expected_ids}, got {actual_ids}"
    assert len(result) == 3
    assert all(m["healthy"] is True for m in result)
