"""Unified node health rollup.

A node carries two *independent* reachability signals that are written by two
different subsystems:

- ``status``    — Salt minion presence (push): online / stale / offline / unknown.
                  Answers "is the agent phoning home?".
- ``ssh_state`` — direct SSH probe (pull): ok / auth_failed / unreachable / unknown.
                  Answers "can we reach and authenticate to the box right now?".

Operators kept asking "is this node actually healthy?" and had to mentally
combine the two. :func:`compute_health` does that combination once, server-side,
so the dashboard, the node detail page, the LLM context and any metrics all agree
on a single rollup. The granular signals are still carried on the response for
the hover/drill-down — this only adds a derived read, it never replaces them.

Rollup rule (worst-of, with "unknown" meaning *no data* rather than *failure*):

- ``maintenance`` — node is in maintenance mode (overrides everything; neutral).
- ``down``        — Salt offline OR SSH unreachable (we genuinely can't reach it).
- ``degraded``    — Salt stale OR SSH auth_failed (reachable but something's wrong).
- ``online``      — at least one positive signal and nothing bad.
- ``unknown``     — never seen and never probed (no signal either way).
"""

from __future__ import annotations

# Health rollup states (persisted nowhere — derived on read; sent verbatim to the UI).
HEALTH_ONLINE = "online"
HEALTH_DEGRADED = "degraded"
HEALTH_DOWN = "down"
HEALTH_UNKNOWN = "unknown"
HEALTH_MAINTENANCE = "maintenance"

# Per-dimension severity buckets. "unknown" is deliberately absent so a missing
# signal is treated as "no data", never penalised as a failure.
_GOOD = "good"
_DEGRADED = "degraded"
_DOWN = "down"

_PRESENCE_LEVEL = {"online": _GOOD, "stale": _DEGRADED, "offline": _DOWN}
_SSH_LEVEL = {"ok": _GOOD, "auth_failed": _DEGRADED, "unreachable": _DOWN}


def compute_health(
    status: str | None,
    ssh_state: str | None,
    maintenance_mode: bool = False,
) -> str:
    """Roll a node's Salt presence + SSH state into one health value.

    Returns one of ``online`` / ``degraded`` / ``down`` / ``unknown`` /
    ``maintenance``. Pure and total — any unrecognised input degrades to the
    "no data" bucket rather than raising.
    """
    if maintenance_mode:
        return HEALTH_MAINTENANCE

    levels = [
        _PRESENCE_LEVEL.get(status or ""),
        _SSH_LEVEL.get(ssh_state or ""),
    ]

    if _DOWN in levels:
        return HEALTH_DOWN
    if _DEGRADED in levels:
        return HEALTH_DEGRADED
    if _GOOD in levels:
        return HEALTH_ONLINE
    return HEALTH_UNKNOWN


def health_case(model):
    """SQL ``CASE`` mirroring :func:`compute_health` for one Node model/alias.

    Lets the API filter on the derived rollup in-database (so pagination stays
    correct) instead of computing it per-row in Python after the fact. The WHEN
    ordering encodes the same worst-of precedence as :func:`compute_health`.
    """
    from sqlalchemy import case, or_

    return case(
        (model.maintenance_mode.is_(True), HEALTH_MAINTENANCE),
        (or_(model.status == "offline", model.ssh_state == "unreachable"), HEALTH_DOWN),
        (or_(model.status == "stale", model.ssh_state == "auth_failed"), HEALTH_DEGRADED),
        (or_(model.status == "online", model.ssh_state == "ok"), HEALTH_ONLINE),
        else_=HEALTH_UNKNOWN,
    )


def health_sort_rank(model):
    """SQL ``CASE`` ranking health by severity for ORDER BY (worst = highest).

    ``desc`` therefore surfaces nodes needing attention first: down > degraded >
    unknown > maintenance > online.
    """
    from sqlalchemy import case

    label = health_case(model)
    return case(
        (label == HEALTH_DOWN, 4),
        (label == HEALTH_DEGRADED, 3),
        (label == HEALTH_UNKNOWN, 2),
        (label == HEALTH_MAINTENANCE, 1),
        else_=0,  # online
    )
