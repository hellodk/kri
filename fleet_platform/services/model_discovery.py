"""Discover available models from a live LLM provider endpoint."""
from __future__ import annotations

import logging

import httpx

from fleet_platform.services.llm_caller import normalize_openai_base_url

_log = logging.getLogger(__name__)
_TIMEOUT = 8.0


async def discover_models(url: str, provider: str) -> list[dict]:
    """Query provider's model-list API. Returns [] on any error (never raises).

    Each entry: {"id": str, "name": str, "context_length": int, "capabilities": list[str]}
    context_length/capabilities default to 0/[] when the provider omits them (#273).
    """
    base = normalize_openai_base_url(url)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            if provider == "ollama":
                resp = await client.get(f"{base}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                return [
                    {"id": m["name"], "name": m["name"], "context_length": 0, "capabilities": []}
                    for m in data.get("models", [])
                ]
            else:
                # vllm, llamacpp, openai_compat — OpenAI /v1/models format
                # exo also returns context_length and capabilities per model
                resp = await client.get(f"{base}/v1/models")
                resp.raise_for_status()
                data = resp.json()
                return [
                    {
                        "id": m["id"],
                        "name": m.get("name", m["id"]),
                        "context_length": int(m.get("context_length", 0) or 0),
                        "capabilities": list(m.get("capabilities", []) or []),
                    }
                    for m in data.get("data", [])
                ]
    except Exception as exc:
        _log.debug("model_discovery: could not reach %s (%s): %s", url, provider, exc)
        return []
