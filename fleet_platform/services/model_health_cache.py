"""In-process health cache for discovered LLM models.

Key: (base_url, provider, model_id)
TTL: 5 minutes (300 s)
Thread-safety: single-process asyncio only — no locks needed.
"""

from __future__ import annotations

import time as _time_mod
from typing import TypedDict

_TTL = 300.0


class _Entry(TypedDict):
    healthy: bool
    latency_ms: int | None
    ts: float


_cache: dict[tuple[str, str, str], _Entry] = {}


def _now() -> float:
    return _time_mod.monotonic()


def set_health(
    base_url: str,
    provider: str,
    model_id: str,
    healthy: bool,
    latency_ms: int | None,
) -> None:
    _cache[(base_url, provider, model_id)] = {
        "healthy": healthy,
        "latency_ms": latency_ms,
        "ts": _now(),
    }


def get_healthy_models(base_url: str, provider: str) -> list[dict]:
    """Return fresh healthy models sorted by latency (None sorts last)."""
    now = _now()
    results = [
        {"id": k[2], "latency_ms": v["latency_ms"]}
        for k, v in _cache.items()
        if k[0] == base_url and k[1] == provider and v["healthy"] and (now - v["ts"]) < _TTL
    ]
    return sorted(results, key=lambda m: (m["latency_ms"] is None, m["latency_ms"] or 0))


def evict(base_url: str, provider: str, model_id: str) -> None:
    """Remove a single entry — called when dispatch fails."""
    _cache.pop((base_url, provider, model_id), None)


def is_stale(base_url: str, provider: str) -> bool:
    """True when no fresh entry exists for this endpoint."""
    now = _now()
    return not any(k[0] == base_url and k[1] == provider and (now - v["ts"]) < _TTL for k, v in _cache.items())


def clear() -> None:
    """Wipe the cache — for tests only."""
    _cache.clear()
