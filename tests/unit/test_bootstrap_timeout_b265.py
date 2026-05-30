"""Tests for #265: bootstrap timeout reduced to 10 minutes."""
import ast
from pathlib import Path


def _ansible_tasks_src() -> str:
    return Path("fleet_platform/workers/ansible_tasks.py").read_text()


def _ansible_route_src() -> str:
    return Path("fleet_platform/api/routes/ansible.py").read_text()


def test_bootstrap_timeout_constant_exists():
    src = _ansible_tasks_src()
    assert "_BOOTSTRAP_TIMEOUT_SECONDS" in src, (
        "Must define _BOOTSTRAP_TIMEOUT_SECONDS constant"
    )


def test_bootstrap_timeout_is_600():
    src = _ansible_tasks_src()
    # Find the constant assignment
    for line in src.splitlines():
        if "_BOOTSTRAP_TIMEOUT_SECONDS" in line and "=" in line and "#" not in line.split("=")[0]:
            value = line.split("=")[1].strip().split()[0].rstrip(",")
            assert value == "600", (
                f"_BOOTSTRAP_TIMEOUT_SECONDS must be 600 (10 min), got {value}"
            )
            return
    raise AssertionError("_BOOTSTRAP_TIMEOUT_SECONDS constant not found with assignment")


def test_ansible_runner_uses_timeout_constant():
    src = _ansible_tasks_src()
    assert "timeout=_BOOTSTRAP_TIMEOUT_SECONDS" in src or "timeout=_BOOTSTRAP_TIMEOUT_SECONDS," in src, (
        "ansible_runner.run() must use timeout=_BOOTSTRAP_TIMEOUT_SECONDS"
    )


def test_timeout_error_message_says_10_minutes():
    src = _ansible_tasks_src()
    assert "10 minutes" in src, (
        "Timeout error message must say '10 minutes'"
    )
    assert "20 minutes" not in src, (
        "Old '20 minutes' message must be replaced"
    )


def test_stale_cutoff_is_at_most_15_minutes():
    src = _ansible_route_src()
    # Find timedelta usage in bootstrap_status route
    for line in src.splitlines():
        if "stale_cutoff" in line and "timedelta" in line and "minutes" in line:
            # Extract the minutes value
            import re
            m = re.search(r"minutes\s*=\s*(\d+)", line)
            if m:
                minutes = int(m.group(1))
                assert minutes <= 15, (
                    f"Stale cutoff must be ≤ 15 minutes (bootstrap timeout is 10 min), got {minutes}"
                )
                return
    raise AssertionError("stale_cutoff timedelta not found in bootstrap_status route")
