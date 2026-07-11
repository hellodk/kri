"""Unit tests for issue #536 — node-vantage master reachability.

Tests:
  - parse_nc_reachability: rc 0 → True; non-zero → False; mixed list.
  - playbooks/tasks/host_prep_gate.yml: contains a node-side reachability
    check over salt_masters and a fail-when-none-reachable guard, run before
    the salt_minion role.

Roles-refactor Phase 3 (§9 #2): the reachability check moved out of the
bootstrap_node.yml monolith into playbooks/tasks/host_prep_gate.yml, and its
implementation changed from two `nc -z` shell loops to a single
`ansible.builtin.wait_for` loop over `salt_masters | product([4505, 4506])`.
The behavioural contract (probe both ports for every master; fail the play
only when NONE are reachable; run before minion config is written) is
unchanged — only the underlying module is more robust. The class below
verifies the new implementation preserves that contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleet_platform.services.reachability import parse_nc_reachability

# ---------------------------------------------------------------------------
# parse_nc_reachability unit tests
# ---------------------------------------------------------------------------


class TestParseNcReachability:
    def test_rc_zero_is_reachable(self) -> None:
        results = [{"master": "10.0.0.1", "rc": 0}]
        assert parse_nc_reachability(results) == {"10.0.0.1": True}

    def test_rc_nonzero_is_not_reachable(self) -> None:
        results = [{"master": "10.0.0.2", "rc": 1}]
        assert parse_nc_reachability(results) == {"10.0.0.2": False}

    def test_rc_nonzero_various_codes(self) -> None:
        """Any non-zero rc (1, 2, 255) must map to False."""
        for rc in (1, 2, 255):
            results = [{"master": "192.168.1.100", "rc": rc}]
            assert parse_nc_reachability(results) == {"192.168.1.100": False}, f"rc={rc} should map to False"

    def test_mixed_list_mapped_correctly(self) -> None:
        results = [
            {"master": "10.0.0.1", "rc": 0},
            {"master": "10.0.0.2", "rc": 1},
            {"master": "10.0.0.3", "rc": 0},
            {"master": "10.0.0.4", "rc": 255},
        ]
        expected = {
            "10.0.0.1": True,
            "10.0.0.2": False,
            "10.0.0.3": True,
            "10.0.0.4": False,
        }
        assert parse_nc_reachability(results) == expected

    def test_empty_list_returns_empty_dict(self) -> None:
        assert parse_nc_reachability([]) == {}

    def test_all_reachable(self) -> None:
        results = [{"master": f"10.0.0.{i}", "rc": 0} for i in range(1, 4)]
        result = parse_nc_reachability(results)
        assert all(result.values())
        assert len(result) == 3

    def test_none_reachable(self) -> None:
        results = [{"master": f"10.0.0.{i}", "rc": 1} for i in range(1, 4)]
        result = parse_nc_reachability(results)
        assert not any(result.values())
        assert len(result) == 3


# ---------------------------------------------------------------------------
# host_prep_gate.yml source assertions (#536, updated for roles-refactor Phase 3)
# ---------------------------------------------------------------------------

_GATE_PATH = Path(__file__).parents[2] / "playbooks" / "tasks" / "host_prep_gate.yml"
_PLAYBOOK_PATH = Path(__file__).parents[2] / "playbooks" / "bootstrap_node.yml"


@pytest.fixture(scope="module")
def gate_text() -> str:
    return _GATE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def playbook_text() -> str:
    return _PLAYBOOK_PATH.read_text(encoding="utf-8")


class TestBootstrapPlaybookNodeVantage:
    def test_gate_file_exists(self) -> None:
        assert _GATE_PATH.exists(), f"Gate task file not found: {_GATE_PATH}"

    def test_wait_for_check_present(self, gate_text: str) -> None:
        """Gate must use ansible.builtin.wait_for for the node-vantage TCP probe."""
        assert "wait_for" in gate_text, "host_prep_gate.yml must contain a wait_for task for the node-vantage TCP probe"
        assert "nc -z" not in gate_text, "host_prep_gate.yml must not use nc -z (replaced by wait_for, §9 #2)"

    def test_wait_for_loops_over_salt_masters(self, gate_text: str) -> None:
        """The wait_for check must loop over the salt_masters variable (via product)."""
        assert "salt_masters" in gate_text, "host_prep_gate.yml must reference 'salt_masters' for the loop"
        assert "product(" in gate_text, "host_prep_gate.yml must build the master x port pairs with the product filter"
        assert "loop:" in gate_text, "host_prep_gate.yml must use a loop construct for the wait_for checks"

    def test_checks_port_4505(self, gate_text: str) -> None:
        assert "4505" in gate_text, "host_prep_gate.yml must probe port 4505 (Salt publish)"

    def test_checks_port_4506(self, gate_text: str) -> None:
        assert "4506" in gate_text, "host_prep_gate.yml must probe port 4506 (Salt return)"

    def test_fail_when_none_reachable_guard_present(self, gate_text: str) -> None:
        """Gate must fail the play if no master is reachable."""
        assert "fail:" in gate_text or "ansible.builtin.fail:" in gate_text, (
            "host_prep_gate.yml must have a 'fail:' task when no master is reachable"
        )

    def test_fail_guard_message_mentions_network_firewall(self, gate_text: str) -> None:
        """The failure message must mention network/firewall to aid diagnosis."""
        assert "network" in gate_text.lower() or "firewall" in gate_text.lower(), (
            "host_prep_gate.yml fail task must mention 'network' or 'firewall'"
        )

    def test_gate_runs_before_salt_minion_role(self, playbook_text: str) -> None:
        """The reachability gate must run before the salt_minion role (pre_tasks before roles)."""
        gate_pos = playbook_text.find("host_prep_gate.yml")
        roles_pos = playbook_text.find("- salt_minion")
        assert gate_pos != -1, "bootstrap_node.yml must import tasks/host_prep_gate.yml"
        assert roles_pos != -1, "bootstrap_node.yml must list the salt_minion role"
        assert gate_pos < roles_pos, (
            "host_prep_gate.yml import must appear BEFORE the salt_minion role in bootstrap_node.yml"
        )
