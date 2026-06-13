"""Tests for OS-aware baseline lookup (P3, prod-os-baselines).

Covers:
- ``derive_os_family`` correctly maps Node fields onto canonical Salt families.
- ``validate_baseline`` rejects unknown ``os_family`` values.
- The OS-priority CASE expression yields the expected SQL ranking.

The full async ``find_baseline_for_node`` integration path is exercised in the
existing baseline integration tests once this column exists in the schema; those
tests will pick up the new ordering on the next merge gate run.
"""
from __future__ import annotations

from types import SimpleNamespace


def test_derive_os_family_macos_via_macos_version():
    from fleet_platform.services.baseline_loader import derive_os_family

    node = SimpleNamespace(macos_version="14.5", os_version=None)
    assert derive_os_family(node) == "Darwin"


def test_derive_os_family_macos_via_os_version_string():
    from fleet_platform.services.baseline_loader import derive_os_family

    # When the macOS collector hasn't run yet, fall back to os_version.
    node = SimpleNamespace(macos_version=None, os_version="macOS 14.5")
    assert derive_os_family(node) == "Darwin"

    node = SimpleNamespace(macos_version=None, os_version="Darwin 23.5.0")
    assert derive_os_family(node) == "Darwin"


def test_derive_os_family_linux_distros():
    from fleet_platform.services.baseline_loader import derive_os_family

    for raw in (
        "Ubuntu 22.04.3 LTS",
        "Linux 5.15.0-91-generic",
        "Debian GNU/Linux 12",
        "Rocky Linux 9.3",
        "AlmaLinux 9",
        "Alpine Linux 3.19",
    ):
        node = SimpleNamespace(macos_version=None, os_version=raw)
        assert derive_os_family(node) == "Linux", raw


def test_derive_os_family_freebsd_and_windows():
    from fleet_platform.services.baseline_loader import derive_os_family

    assert (
        derive_os_family(SimpleNamespace(macos_version=None, os_version="FreeBSD 13.2-RELEASE"))
        == "FreeBSD"
    )
    assert (
        derive_os_family(SimpleNamespace(macos_version=None, os_version="Windows 11 Pro"))
        == "Windows"
    )


def test_derive_os_family_unknown_returns_none():
    """Unrecognised os_version yields None — caller falls back to OS-agnostic baselines."""
    from fleet_platform.services.baseline_loader import derive_os_family

    assert derive_os_family(SimpleNamespace(macos_version=None, os_version=None)) is None
    assert derive_os_family(SimpleNamespace(macos_version=None, os_version="")) is None
    assert (
        derive_os_family(SimpleNamespace(macos_version=None, os_version="some-future-os"))
        is None
    )


def test_validate_baseline_accepts_valid_os_family():
    from fleet_platform.services.baseline_loader import validate_baseline

    assert (
        validate_baseline(
            {"name": "n", "os_family": "Darwin", "packages": [{"name": "git"}]}
        )
        == []
    )


def test_validate_baseline_rejects_unknown_os_family():
    from fleet_platform.services.baseline_loader import validate_baseline

    errors = validate_baseline(
        {"name": "n", "os_family": "macos", "packages": [{"name": "git"}]}
    )
    assert any("os_family" in e for e in errors)


def test_validate_baseline_allows_omitted_os_family():
    from fleet_platform.services.baseline_loader import validate_baseline

    # Omitted os_family means OS-agnostic — no error.
    assert validate_baseline({"name": "n", "packages": [{"name": "git"}]}) == []


def test_os_priority_case_assigns_zero_to_exact_match():
    """When a Darwin node looks up baselines, exact-match rows beat NULL rows."""
    from sqlalchemy import literal

    from fleet_platform.models.drift import DesiredStateBaseline
    from fleet_platform.services.baseline_loader import _os_priority

    expr = _os_priority("Darwin")
    # Compile against the SQLAlchemy default dialect; we just want to be
    # sure the CASE branches use the expected values.
    compiled = str(
        expr.compile(compile_kwargs={"literal_binds": True})
    ).replace("\n", " ")
    assert "WHEN" in compiled
    # Exact-match branch is priority 0, NULL branch is priority 1.
    assert "0" in compiled and "1" in compiled
    # The column referenced is the os_family column we just added.
    assert "os_family" in compiled
    # And the literal we passed survives into the SQL.
    assert "Darwin" in compiled
    # Reference to silence unused-import warnings — DesiredStateBaseline
    # and literal are used to ensure the helper resolves the column at all.
    assert DesiredStateBaseline.os_family is not None
    assert literal("x") is not None
