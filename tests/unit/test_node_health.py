"""Unit tests for the unified node health rollup (compute_health).

The rollup combines two independent signals — Salt presence (``status``) and the
SSH probe (``ssh_state``) — into a single worst-of value, where an "unknown"
signal counts as *no data* rather than a failure, and maintenance mode overrides
everything.
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

    def test_online_when_ssh_ok_but_salt_unknown(self):
        # One positive signal, nothing bad → online.
        assert compute_health("unknown", "ok") == HEALTH_ONLINE

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
