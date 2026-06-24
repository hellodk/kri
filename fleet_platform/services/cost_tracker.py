"""Cloud-fallback cost tracking + daily cap (#715).

The local MLX cluster serves ~all traffic at $0; the admin-gated cloud endpoint
is the only spend path. This tracks per-day cloud spend in-process and enforces a
hard daily cap so a degraded local cluster can't run up an unbounded bill. The
tier router consults :func:`can_spend` before returning a cloud endpoint, and the
agent route records spend after a cloud-served run.

In-process state is sufficient as a circuit-breaker cap; the audit log remains the
source of truth for actual usage. Note that each worker process has its own STATE
so the effective cap in a multi-worker deployment is N × DAILY_CAP_USD — size the
cap accordingly or point LLM_COST_REDIS_URL at a Redis instance to share state
across workers (#774 partial mitigation: threading lock eliminates the in-process
data race; cross-process sharing is a follow-up).
"""

from __future__ import annotations

import os
import threading
from datetime import date
from typing import Any

# Rough blended $/1K tokens for the cloud fallback model; override via env.
COST_PER_1K_TOKENS_USD = float(os.getenv("AGENT_CLOUD_COST_PER_1K_USD", "0.009"))
DAILY_CAP_USD = float(os.getenv("AGENT_CLOUD_DAILY_CAP_USD", "5.0"))

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


class _CostState:
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

    def record_tokens(self, input_tokens: int, output_tokens: int, *, today: date | None = None) -> float:
        cost = (max(0, input_tokens) + max(0, output_tokens)) / 1000.0 * COST_PER_1K_TOKENS_USD
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


def can_spend() -> bool:
    return STATE.can_spend()


def record_tokens(input_tokens: int, output_tokens: int) -> float:
    return STATE.record_tokens(input_tokens, output_tokens)


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
    """
    if getattr(endpoint, "provider", None) not in CLOUD_PROVIDERS:
        return 0.0
    target = state if state is not None else STATE
    return target.record_tokens(input_tokens, output_tokens)


def snapshot() -> dict:
    return STATE.snapshot()
