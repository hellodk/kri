"""Unified node health rollup.

A node carries up to three *independent* health signals, written by different
subsystems:

- ``status``    — Salt **minion** presence (push): online / stale / offline / unknown.
                  The *primary* signal — "is this node a working, managed member of
                  the fleet?". Set by ``manage.up`` presence sync and grain ingest.
- ``ssh_state`` — direct **SSH** probe (pull): ok / auth_failed / unreachable / unknown.
                  A *secondary* signal — "can we reach the box directly for remediation?".
- master status — for nodes that *run* a salt-master, the control-plane health
                  (``SaltMaster.status``): healthy / degraded / unreachable / unknown.
                  Covers salt-api auth, ports 4505/4506, key store, etc.

:func:`compute_health` rolls these into a single worst-of value so the dashboard,
node detail and metrics agree on one read. The granular signals are still carried
on the response for the hover/drill-down — this only adds a derived read.

Key principle: **minion presence is primary**. SSH-reachable but never-seen-by-Salt
is *not* "Online" — the box is up but its minion isn't reporting (down, or an id
mismatch), which is exactly what an operator needs to see. So green requires the
minion to actually be reporting; a positive secondary signal alone only earns
``degraded``. A *missing* secondary signal, by contrast, never penalises a node
that is otherwise good.

Rollup states: ``online`` / ``degraded`` / ``down`` / ``unknown`` / ``maintenance``.
"""

from __future__ import annotations

# Health rollup states (persisted nowhere — derived on read; sent verbatim to the UI).
HEALTH_ONLINE = "online"
HEALTH_DEGRADED = "degraded"
HEALTH_DOWN = "down"
HEALTH_UNKNOWN = "unknown"
HEALTH_MAINTENANCE = "maintenance"

# Per-dimension severity buckets.
_GOOD = "good"
_WARN = "warn"
_BAD = "bad"

_MINION_LEVEL = {"online": _GOOD, "stale": _WARN, "offline": _BAD}
_SSH_LEVEL = {"ok": _GOOD, "auth_failed": _WARN, "unreachable": _BAD}
_MASTER_LEVEL = {"healthy": _GOOD, "degraded": _WARN, "unreachable": _BAD}


def compute_health(
    status: str | None,
    ssh_state: str | None,
    maintenance_mode: bool = False,
    master_status: str | None = None,
) -> str:
    """Roll a node's minion presence + SSH + (optional) master health into one value.

    ``master_status`` is supplied only for nodes that run a salt-master; ``None``
    means the node is not a master and that dimension is absent.

    Returns one of ``online`` / ``degraded`` / ``down`` / ``unknown`` /
    ``maintenance``. Pure and total — unrecognised inputs degrade to the "no data"
    bucket rather than raising.
    """
    if maintenance_mode:
        return HEALTH_MAINTENANCE

    minion_level = _MINION_LEVEL.get(status or "")
    levels = [minion_level, _SSH_LEVEL.get(ssh_state or "")]
    if master_status is not None:
        levels.append(_MASTER_LEVEL.get(master_status or ""))

    if _BAD in levels:
        return HEALTH_DOWN
    if _WARN in levels:
        return HEALTH_DEGRADED
    if minion_level == _GOOD:
        return HEALTH_ONLINE
    if _GOOD in levels:
        # Reachable by some signal, but the primary (minion presence) is NOT online
        # — e.g. SSH-ok but Salt never saw it. Surface it, never call it green.
        return HEALTH_DEGRADED
    return HEALTH_UNKNOWN


def health_case(model, master_status=None):
    """SQL ``CASE`` mirroring :func:`compute_health` for one Node model/alias.

    Lets the API filter on the derived rollup in-database (so pagination stays
    correct) instead of computing it per-row in Python. ``master_status`` is a SQL
    expression (typically a correlated scalar subquery over ``salt_masters``) that
    resolves to the master control-plane status, or NULL for non-master nodes —
    NULL never matches the master conditions, so the dimension is simply absent.
    """
    from sqlalchemy import case, or_

    bad = or_(model.status == "offline", model.ssh_state == "unreachable")
    warn = or_(model.status == "stale", model.ssh_state == "auth_failed")
    good_any = or_(model.status == "online", model.ssh_state == "ok")
    if master_status is not None:
        bad = or_(bad, master_status == "unreachable")
        warn = or_(warn, master_status == "degraded")
        good_any = or_(good_any, master_status == "healthy")

    return case(
        (model.maintenance_mode.is_(True), HEALTH_MAINTENANCE),
        (bad, HEALTH_DOWN),
        (warn, HEALTH_DEGRADED),
        (model.status == "online", HEALTH_ONLINE),
        (good_any, HEALTH_DEGRADED),
        else_=HEALTH_UNKNOWN,
    )


def health_sort_rank(model, master_status=None):
    """SQL ``CASE`` ranking health by severity for ORDER BY (worst = highest).

    ``desc`` therefore surfaces nodes needing attention first: down > degraded >
    unknown > maintenance > online.
    """
    from sqlalchemy import case

    label = health_case(model, master_status)
    return case(
        (label == HEALTH_DOWN, 4),
        (label == HEALTH_DEGRADED, 3),
        (label == HEALTH_UNKNOWN, 2),
        (label == HEALTH_MAINTENANCE, 1),
        else_=0,  # online
    )
