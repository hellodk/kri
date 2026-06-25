"""Unit tests for the health-rollup aggregation in the fleet overview endpoint.

The summary tiles must agree with the per-node HealthBadge, which is driven by
``compute_health`` (worst-of Salt presence + SSH + maintenance). These tests
mock the DB/Redis dependencies and drive ``fleet_overview`` directly so we
exercise the real aggregation code (not a re-implementation), asserting that the
health_* counts match ``compute_health`` for representative status/ssh combos
while the legacy salt-status counts remain untouched for backward compatibility.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fleet_platform.api.routes.fleet import fleet_overview


def _agg_result(**overrides):
    """Mock the salt-status + drift aggregate query result (`.one()`)."""
    row = SimpleNamespace(
        total=0,
        online=0,
        stale=0,
        offline=0,
        unknown=0,
        avg_drift=0,
        clean=0,
        low=0,
        medium=0,
        high=0,
        critical=0,
    )
    for k, v in overrides.items():
        setattr(row, k, v)
    result = MagicMock()
    result.one.return_value = row
    return result


def _health_result(rows):
    """Mock the per-node (status, ssh_state, maintenance_mode) scan (`.all()`)."""
    result = MagicMock()
    result.all.return_value = rows
    return result


async def test_salt_online_but_ssh_failing_diverges():
    """4 salt-online nodes, 3 with failing SSH: salt says 4 online, health says 1."""
    agg = _agg_result(total=4, online=4)
    health_rows = [
        ("online", "ok", False),  # online
        ("online", "auth_failed", False),  # degraded (ssh warn)
        ("online", "unreachable", False),  # down (ssh bad)
        ("online", "unreachable", False),  # down (ssh bad)
    ]
    db = AsyncMock()
    db.execute.side_effect = [agg, _health_result(health_rows)]
    redis = AsyncMock()
    redis.get.return_value = None

    data = await fleet_overview(db=db, redis=redis, _={"sub": "t"})

    # Legacy salt-presence counts are preserved (backward compat).
    assert data.online == 4
    assert data.total_nodes == 4
    # Health rollup tells the real story shown on the per-node badges.
    assert data.health_online == 1
    assert data.health_degraded == 1
    assert data.health_down == 2
    assert data.health_unknown == 0
    assert data.health_maintenance == 0


async def test_all_health_buckets_counted():
    """Cover every rollup outcome including the 'missing ssh never penalises' rule."""
    agg = _agg_result(total=8, online=4, stale=1, offline=1, unknown=1)
    health_rows = [
        ("online", "ok", False),  # online
        ("online", None, False),  # online (null ssh does NOT downgrade)
        ("stale", "ok", False),  # degraded (presence warn)
        ("online", "auth_failed", False),  # degraded (ssh warn)
        ("offline", "ok", False),  # down (presence bad)
        ("online", "unreachable", False),  # down (ssh bad)
        ("unknown", None, False),  # unknown (no good/warn/bad signal)
        (None, None, True),  # maintenance (overrides everything)
    ]
    db = AsyncMock()
    db.execute.side_effect = [agg, _health_result(health_rows)]
    redis = AsyncMock()
    redis.get.return_value = None

    data = await fleet_overview(db=db, redis=redis, _={"sub": "t"})

    assert data.health_online == 2
    assert data.health_degraded == 2
    assert data.health_down == 2
    assert data.health_unknown == 1
    assert data.health_maintenance == 1
    # Counts sum to the number of nodes scanned.
    total_health = (
        data.health_online + data.health_degraded + data.health_down + data.health_unknown + data.health_maintenance
    )
    assert total_health == len(health_rows)

    # New payload still carries the legacy fields, and serializes them for cache.
    cached = redis.setex.await_args.args[2]
    assert '"health_online"' in cached
    assert '"online"' in cached


async def test_empty_fleet_zeroes_all_health_counts():
    agg = _agg_result(total=0)
    db = AsyncMock()
    db.execute.side_effect = [agg, _health_result([])]
    redis = AsyncMock()
    redis.get.return_value = None

    data = await fleet_overview(db=db, redis=redis, _={"sub": "t"})

    assert data.total_nodes == 0
    assert data.health_online == 0
    assert data.health_degraded == 0
    assert data.health_down == 0
    assert data.health_unknown == 0
    assert data.health_maintenance == 0
