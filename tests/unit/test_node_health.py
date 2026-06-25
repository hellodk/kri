"""Unit tests for the unified node health rollup (compute_health).

The rollup combines minion presence (``status``), the SSH probe (``ssh_state``)
and — for master nodes — the salt-master control-plane status into a single
worst-of value. Minion presence is the *primary* signal: green requires it to be
online; a positive secondary signal (SSH/master) alone only earns ``degraded``,
while a *missing* secondary signal never penalises an otherwise-good node.
Maintenance mode overrides everything.
"""

import pytest

from fleet_platform.services.node_health import (
    HEALTH_DEGRADED,
    HEALTH_DOWN,
    HEALTH_MAINTENANCE,
    HEALTH_ONLINE,
    HEALTH_UNKNOWN,
    compute_health,
)


class TestComputeHealth:
    def test_online_when_both_good(self):
        assert compute_health("online", "ok") == HEALTH_ONLINE

    def test_maintenance_overrides_everything(self):
        # Even a hard failure is suppressed while in maintenance mode.
        assert compute_health("offline", "unreachable", maintenance_mode=True) == HEALTH_MAINTENANCE
        assert compute_health("online", "ok", maintenance_mode=True) == HEALTH_MAINTENANCE

    @pytest.mark.parametrize(
        "status,ssh_state",
        [
            ("offline", "ok"),  # Salt down even though SSH works → still needs attention
            ("online", "unreachable"),  # box not reachable directly
            ("offline", "unreachable"),
            ("stale", "unreachable"),
        ],
    )
    def test_down_when_any_dimension_is_down(self, status, ssh_state):
        assert compute_health(status, ssh_state) == HEALTH_DOWN

    @pytest.mark.parametrize(
        "status,ssh_state",
        [
            ("online", "auth_failed"),  # reachable but creds rejected
            ("stale", "ok"),  # heartbeat lagging but SSH fine
            ("stale", "auth_failed"),
        ],
    )
    def test_degraded_when_soft_problem_and_nothing_down(self, status, ssh_state):
        assert compute_health(status, ssh_state) == HEALTH_DEGRADED

    def test_down_beats_degraded(self):
        # stale (degraded) + unreachable (down) → worst-of wins.
        assert compute_health("stale", "unreachable") == HEALTH_DOWN

    @pytest.mark.parametrize("ssh_state", ["unknown", None])
    def test_online_not_penalised_for_unprobed_ssh(self, ssh_state):
        # Salt online + SSH never probed → don't penalise a probe that hasn't run.
        assert compute_health("online", ssh_state) == HEALTH_ONLINE

    @pytest.mark.parametrize("ssh_state", ["ok", "auth_failed"])
    def test_degraded_when_reachable_but_salt_never_seen(self, ssh_state):
        # Minion is the primary signal: SSH-reachable but Salt never saw it is NOT
        # online — surface it as degraded ("minion not reporting").
        assert compute_health("unknown", ssh_state) == HEALTH_DEGRADED

    @pytest.mark.parametrize(
        "status,ssh_state",
        [
            ("unknown", "unknown"),
            ("unknown", None),
            (None, None),
            ("garbage", "garbage"),  # unrecognised inputs degrade to no-data, never raise
        ],
    )
    def test_unknown_when_no_signal_either_way(self, status, ssh_state):
        assert compute_health(status, ssh_state) == HEALTH_UNKNOWN


class TestMasterDimension:
    """Master nodes fold salt-master control-plane health into the rollup."""

    def test_online_when_minion_ssh_and_master_all_good(self):
        assert compute_health("online", "ok", master_status="healthy") == HEALTH_ONLINE

    def test_down_when_master_api_unreachable_even_if_minion_online(self):
        # A master whose control-plane is unreachable is Down even if its
        # co-located minion happens to still report.
        assert compute_health("online", "ok", master_status="unreachable") == HEALTH_DOWN

    def test_degraded_when_master_degraded(self):
        assert compute_health("online", "ok", master_status="degraded") == HEALTH_DEGRADED

    def test_master_unknown_does_not_penalise_otherwise_good_node(self):
        assert compute_health("online", "ok", master_status="unknown") == HEALTH_ONLINE

    def test_master_healthy_but_minion_not_reporting_is_degraded(self):
        # Control-plane healthy, but the node's own minion isn't reporting → degraded.
        assert compute_health("unknown", "unknown", master_status="healthy") == HEALTH_DEGRADED

    def test_non_master_ignores_master_dimension(self):
        # master_status=None means "not a master" — dimension absent.
        assert compute_health("online", "ok", master_status=None) == HEALTH_ONLINE
