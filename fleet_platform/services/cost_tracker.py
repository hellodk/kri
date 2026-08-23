"""Cloud-fallback cost tracking + daily cap (#715, #1030).

The local MLX cluster serves ~all traffic at $0; the admin-gated cloud endpoint
is the only spend path. This tracks per-day cloud spend via Redis (shared across
workers) with fallback to in-process state when Redis is unavailable. The tier
router consults :func:`can_spend` before returning a cloud endpoint, and the
agent route records spend after a cloud-served run.

Redis key: ``kri:llm:spend:YYYY-MM-DD`` with 48h TTL.  Falls back to in-process
``_CostState`` when Redis is unreachable (fail-open for availability).
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)

# Legacy blended $/1K tokens; override via env. Now serves as the fallback
# rate for unknown provider/model pairs (#1048), expressed per 1M tokens.
COST_PER_1K_TOKENS_USD = float(os.getenv("AGENT_CLOUD_COST_PER_1K_USD", "0.009"))
DAILY_CAP_USD = float(os.getenv("AGENT_CLOUD_DAILY_CAP_USD", "5.0"))

# Per-provider/model rates in USD per 1M tokens (input, output) (#1048).
# Matched case-insensitively by substring against the model name; the most
# specific (cheapest) match wins, so gpt-4o-mini is checked before gpt-4o.
COST_PER_1M_USD: dict[tuple[str, str], tuple[float, float]] = {
    ("anthropic", "haiku"): (0.80, 4.00),
    ("anthropic", "sonnet"): (3.00, 15.00),
    ("openai", "gpt-4o-mini"): (0.15, 0.60),
    ("openai", "gpt-4o"): (2.50, 10.00),
}

# Substring probes tried in order — first hit selects the table row above.
_MODEL_RATE_PROBES: tuple[str, ...] = (
    "gpt-4o-mini",
    "gpt-4o",
    "haiku",
    "sonnet",
)


def blended_rate() -> tuple[float, float]:
    """Fallback (input, output) $/1M for unknown provider/model pairs (#1048)."""
    blended = COST_PER_1K_TOKENS_USD * 1000.0
    return (blended, blended)


def rate_for(provider: str | None, model: str | None) -> tuple[float, float]:
    """Return the (input, output) USD-per-1M-token rate for an endpoint (#1048).

    Known classes (anthropic haiku/sonnet, openai gpt-4o class) use published
    list prices; anything else falls back to the legacy blended rate.
    """
    p = (provider or "").strip().lower()
    m = (model or "").strip().lower()
    if p == "anthropic":
        for probe in ("haiku", "sonnet"):
            if probe in m:
                return COST_PER_1M_USD[("anthropic", probe)]
    elif p == "openai":
        for probe in _MODEL_RATE_PROBES:
            if probe in m:
                return COST_PER_1M_USD[("openai", probe)]
    return blended_rate()


def _token_cost(
    input_tokens: int,
    output_tokens: int,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> float:
    r_in, r_out = rate_for(provider, model)
    return max(0, input_tokens) / 1_000_000.0 * r_in + max(0, output_tokens) / 1_000_000.0 * r_out


# Redis key TTL — 48h auto-expire stale keys.
_REDIS_KEY_TTL = int(os.getenv("LLM_COST_REDIS_TTL", str(48 * 3600)))

# Providers whose endpoints incur real spend and must be tracked (#780).
CLOUD_PROVIDERS: frozenset[str] = frozenset(
    {
        "openai",
        "anthropic",
        "google",
        "azure",
        "cohere",
        "mistral",
        "groq",
        "together",
        "perplexity",
    }
)


def _redis_key(today: date | None = None) -> str:
    d = today or date.today()
    return f"kri:llm:spend:{d.isoformat()}"


def _get_redis():
    """Return a sync Redis connection or None if unavailable."""
    try:
        import redis as sync_redis

        from fleet_platform.core.config import settings

        redis_url = getattr(settings, "llm_cost_redis_url", None) or getattr(settings, "redis_url", None)
        if not redis_url:
            return None
        return sync_redis.Redis.from_url(redis_url, socket_connect_timeout=2)
    except Exception:  # noqa: BLE001
        return None


class _CostState:
    """In-process fallback when Redis is unavailable."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._day: date | None = None
        self._spend_usd: float = 0.0

    def _roll(self, today: date) -> None:
        """Roll the accumulator when the calendar day changes (call under lock)."""
        if self._day != today:
            self._day = today
            self._spend_usd = 0.0

    def today_spend(self, *, today: date | None = None) -> float:
        with self._lock:
            self._roll(today or date.today())
            return self._spend_usd

    def can_spend(self, *, today: date | None = None) -> bool:
        return self.today_spend(today=today) < DAILY_CAP_USD

    def record_tokens(
        self,
        input_tokens: int,
        output_tokens: int,
        *,
        today: date | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> float:
        cost = _token_cost(input_tokens, output_tokens, provider=provider, model=model)
        with self._lock:
            self._roll(today or date.today())
            self._spend_usd += cost
        return cost

    def snapshot(self, *, today: date | None = None) -> dict:
        spend = self.today_spend(today=today)
        return {
            "date": (self._day or date.today()).isoformat(),
            "spend_usd": round(spend, 4),
            "daily_cap_usd": DAILY_CAP_USD,
            "remaining_usd": round(max(0.0, DAILY_CAP_USD - spend), 4),
            "capped": spend >= DAILY_CAP_USD,
        }

    def reset(self) -> None:
        with self._lock:
            self._day = None
            self._spend_usd = 0.0


STATE = _CostState()


def can_spend(*, today: date | None = None) -> bool:
    """Check if daily spend is below the cap. Uses Redis when available."""
    r = _get_redis()
    if r is not None:
        try:
            raw = r.get(_redis_key(today))
            spend = float(raw) if raw else 0.0
            return spend < DAILY_CAP_USD
        except Exception:  # noqa: BLE001
            logger.debug("can_spend: Redis read failed, falling back to local state")
    return STATE.can_spend(today=today)


def record_tokens(
    input_tokens: int,
    output_tokens: int,
    *,
    today: date | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> float:
    """Record token spend. Uses Redis INCRBY when available, falls back to local.

    ``provider``/``model`` select the per-model rate table (#1048); omitted
    values keep the legacy blended rate (backwards-compatible signature).
    """
    cost = _token_cost(input_tokens, output_tokens, provider=provider, model=model)
    r = _get_redis()
    if r is not None:
        try:
            key = _redis_key(today)
            r.incrbyfloat(key, cost)
            r.expire(key, _REDIS_KEY_TTL)
            return cost
        except Exception:  # noqa: BLE001
            logger.debug("record_tokens: Redis write failed, falling back to local state")
    return STATE.record_tokens(input_tokens, output_tokens, today=today, provider=provider, model=model)


def record_tokens_for_endpoint(
    input_tokens: int,
    output_tokens: int,
    *,
    endpoint: Any,
    state: _CostState | None = None,
) -> float:
    """Record spend only when the endpoint's provider is a known cloud provider (#780).

    Uses ``endpoint.provider`` (not the routing tag) so direct-UUID endpoint
    selections and non-standard routing tags are both covered.  Returns the cost
    recorded (0.0 for local providers).

    When ``state`` is provided (e.g. in tests), records directly to that
    ``_CostState`` instance instead of the shared Redis/local path.
    """
    if getattr(endpoint, "provider", None) not in CLOUD_PROVIDERS:
        return 0.0
    provider = getattr(endpoint, "provider", None)
    model = getattr(endpoint, "model", None)
    if state is not None:
        return state.record_tokens(input_tokens, output_tokens, provider=provider, model=model)
    return record_tokens(input_tokens, output_tokens, provider=provider, model=model)


def snapshot(*, today: date | None = None) -> dict:
    """Return current spend snapshot. Uses Redis when available."""
    r = _get_redis()
    if r is not None:
        try:
            raw = r.get(_redis_key(today))
            spend = float(raw) if raw else 0.0
            return {
                "date": (today or date.today()).isoformat(),
                "spend_usd": round(spend, 4),
                "daily_cap_usd": DAILY_CAP_USD,
                "remaining_usd": round(max(0.0, DAILY_CAP_USD - spend), 4),
                "capped": spend >= DAILY_CAP_USD,
            }
        except Exception:  # noqa: BLE001
            logger.debug("snapshot: Redis read failed, falling back to local state")
    return STATE.snapshot(today=today)
