"""Unit tests for issue #971 — self-master reachability false-negative fix.

playbooks/tasks/host_prep_gate.yml probes each salt-master from the TARGET's
own vantage point. When a node's own address is listed as a salt_master
(the node IS the master), probing its own LAN IP can false-negative even
though the service is reachable from every other host. This gate must:

  1. Dedupe salt_masters before probing/reporting (avoid double-counting
     "Masters probed: 192.168.1.64, 192.168.1.64").
  2. Resolve self-addressed masters (own IPv4 addresses, default IPv4,
     127.0.0.1/localhost, ansible_hostname/ansible_fqdn) to a 127.0.0.1
     probe instead of the external address.
  3. Preserve fail-only-when-none-reachable semantics.

These are source-inspection tests (no live Ansible run / no real node).
"""

from __future__ import annotations

from pathlib import Path

import pytest

_GATE_PATH = Path(__file__).parents[2] / "playbooks" / "tasks" / "host_prep_gate.yml"


@pytest.fixture(scope="module")
def gate_text() -> str:
    return _GATE_PATH.read_text(encoding="utf-8")


class TestGateDedupesMasters:
    def test_gate_file_exists(self) -> None:
        assert _GATE_PATH.exists(), f"Gate task file not found: {_GATE_PATH}"

    def test_salt_masters_deduped_with_unique_filter(self, gate_text: str) -> None:
        """salt_masters must be passed through the 'unique' filter before use."""
        assert "salt_masters | unique" in gate_text, (
            "host_prep_gate.yml must dedupe salt_masters via the 'unique' filter "
            "before probing/reporting (avoids 'Masters probed: X, X')"
        )

    def test_probe_loop_uses_deduped_masters(self, gate_text: str) -> None:
        """The wait_for probe loop must iterate over the deduped master list, not the raw one."""
        assert "_gate_masters | product(" in gate_text, (
            "host_prep_gate.yml wait_for loop must use the deduped '_gate_masters' "
            "variable with product(), not the raw salt_masters list"
        )

    def test_fail_message_uses_deduped_masters(self, gate_text: str) -> None:
        assert "_gate_masters | join(" in gate_text, (
            "host_prep_gate.yml fail message must list the deduped master set (_gate_masters)"
        )


class TestGateSelfMasterLoopback:
    def test_self_address_fact_computed(self, gate_text: str) -> None:
        """Gate must compute a set of this node's own addresses from gathered facts."""
        assert "_gate_self_addresses" in gate_text, (
            "host_prep_gate.yml must compute a self-address set (_gate_self_addresses) "
            "to detect when a configured master IS this node"
        )
        for fact_name in (
            "ansible_all_ipv4_addresses",
            "ansible_default_ipv4.address",
            "ansible_hostname",
            "ansible_fqdn",
        ):
            assert fact_name in gate_text, (
                f"host_prep_gate.yml self-address computation must reference {fact_name}"
            )

    def test_localhost_and_loopback_included_in_self_set(self, gate_text: str) -> None:
        assert "127.0.0.1" in gate_text
        assert "localhost" in gate_text

    def test_self_master_substituted_with_loopback_in_probe(self, gate_text: str) -> None:
        """The wait_for host must resolve to 127.0.0.1 when the master is one of this node's own addresses."""
        assert "'127.0.0.1' if item.0 in _gate_self_addresses else item.0" in gate_text, (
            "host_prep_gate.yml wait_for task must substitute 127.0.0.1 for any "
            "master address matching this node's own addresses"
        )

    def test_debug_log_shows_original_and_resolved_host(self, gate_text: str) -> None:
        """The reachability log must show both the original master address and the probed host."""
        assert "probed via" in gate_text, (
            "host_prep_gate.yml debug log must show which host was actually probed "
            "(original master address vs. resolved loopback)"
        )


class TestFailOnlyWhenNoneReachablePreserved:
    def test_wait_for_still_used(self, gate_text: str) -> None:
        assert "ansible.builtin.wait_for" in gate_text

    def test_fail_when_all_failed_semantics_preserved(self, gate_text: str) -> None:
        """The fail 'when' must still compare failed-count to total-count (fail only if ALL failed)."""
        assert (
            "master_port_results.results | selectattr('failed') | list | length "
            "== master_port_results.results | length" in gate_text
        ), (
            "host_prep_gate.yml must only fail when the number of failed probes "
            "equals the total number of probes (i.e. NONE reachable)"
        )

    def test_ports_still_probed(self, gate_text: str) -> None:
        assert "4505" in gate_text
        assert "4506" in gate_text

    def test_ignore_errors_preserved(self, gate_text: str) -> None:
        """Individual probe failures must not abort the play before the aggregate fail check runs."""
        assert "ignore_errors: true" in gate_text
