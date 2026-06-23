"""Unit tests for issue #536 — node-vantage master reachability.

Tests:
  - parse_nc_reachability: rc 0 → True; non-zero → False; mixed list.
  - bootstrap_node.yml: contains node-side nc -z check over salt_masters
    and a fail-when-none-reachable guard before the minion-config write.
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
# bootstrap_node.yml source assertions (#536)
# ---------------------------------------------------------------------------

_PLAYBOOK_PATH = Path(__file__).parents[2] / "playbooks" / "bootstrap_node.yml"


@pytest.fixture(scope="module")
def playbook_text() -> str:
    return _PLAYBOOK_PATH.read_text(encoding="utf-8")


class TestBootstrapPlaybookNodeVantage:
    def test_playbook_exists(self) -> None:
        assert _PLAYBOOK_PATH.exists(), f"Playbook not found: {_PLAYBOOK_PATH}"

    def test_nc_z_check_present(self, playbook_text: str) -> None:
        """Playbook must contain an nc -z check iterating over salt_masters."""
        assert "nc -z" in playbook_text, "bootstrap_node.yml must contain 'nc -z' for node-vantage TCP probe"

    def test_nc_loops_over_salt_masters(self, playbook_text: str) -> None:
        """The nc check must loop over the salt_masters variable."""
        assert "salt_masters" in playbook_text, "bootstrap_node.yml must reference 'salt_masters' for the nc loop"
        # The loop + nc should both appear together (not just incidentally)
        assert "loop:" in playbook_text or "with_items:" in playbook_text, (
            "bootstrap_node.yml must use a loop construct for the nc checks"
        )

    def test_nc_checks_port_4505(self, playbook_text: str) -> None:
        assert "4505" in playbook_text, "bootstrap_node.yml must probe port 4505 (Salt publish)"

    def test_nc_checks_port_4506(self, playbook_text: str) -> None:
        assert "4506" in playbook_text, "bootstrap_node.yml must probe port 4506 (Salt return)"

    def test_fail_when_none_reachable_guard_present(self, playbook_text: str) -> None:
        """Playbook must fail the play if no master is reachable."""
        assert "fail:" in playbook_text or "ansible.builtin.fail:" in playbook_text, (
            "bootstrap_node.yml must have a 'fail:' task when no master is reachable"
        )

    def test_fail_guard_message_mentions_network_firewall(self, playbook_text: str) -> None:
        """The failure message must mention network/firewall to aid diagnosis."""
        assert "network" in playbook_text.lower() or "firewall" in playbook_text.lower(), (
            "bootstrap_node.yml fail task must mention 'network' or 'firewall'"
        )

    def test_nc_check_appears_before_minion_config_write(self, playbook_text: str) -> None:
        """The nc reachability check must appear before 'Write Salt minion config'."""
        nc_pos = playbook_text.find("nc -z")
        minion_config_pos = playbook_text.find("Write Salt minion config")
        assert nc_pos != -1, "nc -z not found in playbook"
        assert minion_config_pos != -1, "'Write Salt minion config' task not found"
        assert nc_pos < minion_config_pos, (
            "nc -z reachability check must appear BEFORE 'Write Salt minion config' in the playbook"
        )
