"""Discover available models from a live LLM provider endpoint."""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from fleet_platform.services import model_health_cache as _cache
from fleet_platform.services.llm_caller import normalize_openai_base_url

_log = logging.getLogger(__name__)
_TIMEOUT = 8.0
_PROBE_TIMEOUT = 5.0


async def discover_models(url: str, provider: str) -> list[dict]:
    """Legacy: return model list without health info. Used by get_models() helper."""
    results = await discover_models_with_health(url, provider, api_key=None)
    return [
        {
            "id": m["id"],
            "name": m["name"],
            "context_length": m.get("context_length", 0),
            "capabilities": m.get("capabilities", []),
        }
        for m in results
    ]


async def _probe_model(base_url: str, model_id: str, api_key: str | None) -> tuple[bool, int | None]:
    """Send a 1-token chat request. Returns (healthy, latency_ms)."""
    t0 = time.monotonic()
    try:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            resp = await client.post(
                f"{base_url}/v1/chat/completions",
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 1,
                },
                headers=headers,
            )
            resp.raise_for_status()
        return True, int((time.monotonic() - t0) * 1000)
    except Exception:
        return False, None


async def discover_models_with_health(url: str, provider: str, api_key: str | None) -> list[dict]:
    """Query provider for models and assess health. Populates the health cache.

    Returns list of {id, name, healthy, latency_ms}.
    Returns [] on any error (never raises).
    """
    base = normalize_openai_base_url(url)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            if provider == "ollama":
                resp = await client.get(f"{base}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                models = [
                    {"id": m["name"], "name": m["name"], "healthy": True, "latency_ms": None}
                    for m in data.get("models", [])
                ]
                for m in models:
                    _cache.set_health(url, provider, m["id"], healthy=True, latency_ms=None)
                return models
            else:
                resp = await client.get(f"{base}/v1/models")
                resp.raise_for_status()
                data = resp.json()
                raw_models = data.get("data", [])
                model_ids = [m["id"] for m in raw_models]
                model_meta = {
                    m["id"]: {
                        "name": m.get("name", m["id"]),
                        "context_length": m.get("context_length", 0),
                        "capabilities": m.get("capabilities", []),
                    }
                    for m in raw_models
                }

        # probe all non-Ollama models concurrently
        probes = await asyncio.gather(
            *[_probe_model(base, mid, api_key) for mid in model_ids],
            return_exceptions=False,
        )

        results = []
        for mid, (healthy, latency_ms) in zip(model_ids, probes):
            _cache.set_health(url, provider, mid, healthy=healthy, latency_ms=latency_ms)
            meta = model_meta[mid]
            results.append(
                {
                    "id": mid,
                    "name": meta["name"],
                    "healthy": healthy,
                    "latency_ms": latency_ms,
                    "context_length": meta["context_length"],
                    "capabilities": meta["capabilities"],
                }
            )
        return results

    except Exception as exc:
        _log.debug("model_discovery: could not reach %s (%s): %s", url, provider, exc)
        return []
