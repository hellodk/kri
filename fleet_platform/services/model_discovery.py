"""Discover available models from a live LLM provider endpoint."""

from __future__ import annotations

import logging
import time

import httpx

from fleet_platform.services import model_health_cache as _cache
from fleet_platform.services.llm_caller import normalize_openai_base_url

_log = logging.getLogger(__name__)
_TIMEOUT = 8.0
_PROBE_TIMEOUT = 20.0


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


async def _probe_model(base_url: str, model_id: str, api_key: str | None) -> tuple[bool | None, int | None]:
    """Send a 1-token chat request. Returns a tristate (healthy, latency_ms).

    - (True,  latency_ms) — probe succeeded; model is healthy.
    - (False, None)       — definitive HTTP error (4xx/5xx); model is genuinely broken.
    - (None,  None)       — timeout or connection error; server is busy (e.g. loading the
                            model). The model is NOT marked unhealthy — it was listed by
                            /v1/models so it exists; the caller treats None as healthy.
    """
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
            try:
                body = resp.json()
            except Exception:  # noqa: BLE001
                body = {}

        # A 200 is only healthy when the response contains actual content or
        # at least 1 completion token. A vllm-mlx crash returns HTTP 200 but
        # delivers an empty stream (0 tokens), which would look healthy under
        # the old raise_for_status()-only check (#840).
        choices = body.get("choices") or []
        has_content = any((c.get("message") or {}).get("content") for c in choices)
        completion_tokens = (body.get("usage") or {}).get("completion_tokens") or 0
        if not has_content and completion_tokens < 1:
            return False, None
        return True, int((time.monotonic() - t0) * 1000)
    except httpx.HTTPStatusError:
        # Definitive server-side error — the model is broken.
        return False, None
    except Exception:
        # Timeout, connection error, etc. — server is busy loading; not a failure.
        return None, None


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

        # Probe models SEQUENTIALLY — single-model-serving backends (MLX) cannot
        # handle concurrent probes for different models (forces reload thrash).
        results = []
        for mid in model_ids:
            probe_healthy, latency_ms = await _probe_model(base, mid, api_key)
            # A model listed by /v1/models demonstrably exists. A probe timeout
            # (probe_healthy is None) means the server is busy loading, NOT that
            # the model is unhealthy — keep it selectable. Only a definitive HTTP
            # error (probe_healthy is False) marks it unhealthy.
            healthy = True if probe_healthy is None else probe_healthy
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
