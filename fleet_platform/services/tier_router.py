"""Capability-tag tier router for the local MLX cluster (#712).

The agent serves four tiers from the fleet itself — planner / coder / worker /
embed — each exposed as an OpenAI-compatible ``LLMEndpoint`` tagged via
``model_capabilities`` (comma-separated). This router answers "which endpoint
should serve a request needing capability X right now?" by walking a fallback
chain of tags, filtering to enabled + healthy endpoints, and picking the
least-loaded one. The chain ends at an optional, admin-gated cloud endpoint so a
fully-degraded local cluster never hard-fails an operator (#716 decision d8).

Health and load are tracked in-process (per API worker): a probe failure marks
an endpoint unhealthy for a cooldown window, and an in-flight lease counter
implements least-loaded selection without needing a metrics backend.
"""

from __future__ import annotations

import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.llm_endpoint import LLMEndpoint

# Each capability resolves through a fallback chain of tags, most-specific first.
# A request degrades gracefully down the chain before considering cloud.
CAPABILITY_CHAINS: dict[str, list[str]] = {
    "planner": ["planner", "general"],
    "coder_yaml": ["coder_yaml", "coder", "general"],
    "fast_summarize": ["fast_summarize", "worker", "general"],
    "embed": ["embed"],
}

CLOUD_TAG = "cloud"
_UNHEALTHY_COOLDOWN_S = 60.0


def parse_tags(endpoint: LLMEndpoint) -> set[str]:
    raw = endpoint.model_capabilities or ""
    return {t.strip().lower() for t in raw.split(",") if t.strip()}


class _RouterState:
    """In-process health + load tracking, shared across requests in one worker."""

    def __init__(self) -> None:
        self._load: dict[str, int] = defaultdict(int)
        self._unhealthy_until: dict[str, float] = {}

    def load(self, endpoint_id: str) -> int:
        return self._load.get(endpoint_id, 0)

    def acquire(self, endpoint_id: str) -> None:
        self._load[endpoint_id] += 1

    def release(self, endpoint_id: str) -> None:
        if self._load.get(endpoint_id, 0) > 0:
            self._load[endpoint_id] -= 1

    def mark_unhealthy(self, endpoint_id: str, cooldown_s: float = _UNHEALTHY_COOLDOWN_S) -> None:
        self._unhealthy_until[endpoint_id] = time.monotonic() + cooldown_s

    def mark_healthy(self, endpoint_id: str) -> None:
        self._unhealthy_until.pop(endpoint_id, None)

    def is_healthy(self, endpoint_id: str) -> bool:
        until = self._unhealthy_until.get(endpoint_id)
        if until is None:
            return True
        if time.monotonic() >= until:
            # Cooldown elapsed — give the endpoint another chance.
            self._unhealthy_until.pop(endpoint_id, None)
            return True
        return False

    def reset(self) -> None:
        self._load.clear()
        self._unhealthy_until.clear()


# Module-level singleton (per process).
STATE = _RouterState()


@dataclass
class RouteResult:
    endpoint: LLMEndpoint
    capability: str
    matched_tag: str
    via_cloud: bool


def _select_among(candidates: list[LLMEndpoint]) -> LLMEndpoint | None:
    """Pick the healthy, least-loaded endpoint; ties break toward is_default then name."""
    healthy = [e for e in candidates if STATE.is_healthy(str(e.id))]
    if not healthy:
        return None
    healthy.sort(key=lambda e: (STATE.load(str(e.id)), not e.is_default, e.name or ""))
    return healthy[0]


async def select_endpoint(
    db: AsyncSession,
    capability: str,
    *,
    allow_cloud: bool = False,
) -> RouteResult | None:
    """Resolve ``capability`` to a concrete endpoint, or None if nothing is available.

    Walks the capability's tag chain (local tiers) first; only if every local tag
    is exhausted and ``allow_cloud`` is set does it consider a cloud-tagged endpoint.
    """
    chain = CAPABILITY_CHAINS.get(capability, [capability])
    endpoints = (await db.execute(select(LLMEndpoint).where(LLMEndpoint.enabled.is_(True)))).scalars().all()

    tagged: dict[str, list[LLMEndpoint]] = defaultdict(list)
    cloud_candidates: list[LLMEndpoint] = []
    for e in endpoints:
        tags = parse_tags(e)
        for t in tags:
            tagged[t].append(e)
        if CLOUD_TAG in tags:
            cloud_candidates.append(e)

    for tag in chain:
        chosen = _select_among(tagged.get(tag, []))
        if chosen is not None:
            return RouteResult(endpoint=chosen, capability=capability, matched_tag=tag, via_cloud=False)

    if allow_cloud:
        # The cloud fallback is also gated by the daily spend cap (#715): a
        # degraded local cluster must not run up an unbounded bill.
        from fleet_platform.services import cost_tracker

        if cost_tracker.can_spend():
            chosen = _select_among(cloud_candidates)
            if chosen is not None:
                return RouteResult(endpoint=chosen, capability=capability, matched_tag=CLOUD_TAG, via_cloud=True)

    return None


@contextmanager
def lease(endpoint: LLMEndpoint) -> Iterator[None]:
    """Account one in-flight request against ``endpoint`` for least-loaded routing."""
    eid = str(endpoint.id)
    STATE.acquire(eid)
    try:
        yield
    finally:
        STATE.release(eid)


async def tier_status(db: AsyncSession) -> dict:
    """Snapshot of every capability tier — endpoints, health, current load.

    Drives the observability surface (which minis are serving each tier).
    """
    endpoints = (await db.execute(select(LLMEndpoint).where(LLMEndpoint.enabled.is_(True)))).scalars().all()
    out: dict[str, list[dict]] = {cap: [] for cap in CAPABILITY_CHAINS}
    for cap, chain in CAPABILITY_CHAINS.items():
        for e in endpoints:
            tags = parse_tags(e)
            matched = next((t for t in chain if t in tags), None)
            if matched is None:
                continue
            out[cap].append(
                {
                    "endpoint_id": str(e.id),
                    "name": e.name,
                    "model": e.model,
                    "matched_tag": matched,
                    "healthy": STATE.is_healthy(str(e.id)),
                    "load": STATE.load(str(e.id)),
                }
            )
    return out
