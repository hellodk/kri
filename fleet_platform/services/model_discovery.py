"""Discover available models from a live LLM provider endpoint."""
from __future__ import annotations
import logging
import httpx

from fleet_platform.services.llm_caller import normalize_openai_base_url

_log = logging.getLogger(__name__)
_TIMEOUT = 8.0


async def discover_models(url: str, provider: str) -> list[dict[str, str]]:
    """Query provider's model-list API. Returns [] on any error (never raises)."""
    # Normalize so a base_url written with or without a trailing /v1 resolves
    # to the same endpoint the chat caller uses — no doubled /v1/v1 (#272).
    base = normalize_openai_base_url(url)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            if provider == "ollama":
                resp = await client.get(f"{base}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                return [{"id": m["name"], "name": m["name"]} for m in data.get("models", [])]
            else:
                # vllm, llamacpp, openai_compat all use OpenAI /v1/models format
                resp = await client.get(f"{base}/v1/models")
                resp.raise_for_status()
                data = resp.json()
                return [{"id": m["id"], "name": m["id"]} for m in data.get("data", [])]
    except Exception as exc:
        _log.debug("model_discovery: could not reach %s (%s): %s", url, provider, exc)
        return []
