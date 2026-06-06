"""Tests for frontend/src/lib/saltMasterHelpers.ts — issue #521, epic #523.

Tests the pure helper functions:
- saltMasterBadge(status) → {label, bgClass, textClass}
- isBootstrapBlocked(status) → boolean

Runs the real TypeScript via node --experimental-strip-types.
No mocks — tests the actual implementation.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
HARNESS = Path(__file__).parent / "_salt_master_helpers_harness.ts"
HELPER = ROOT / "frontend/src/lib/saltMasterHelpers.ts"

# (status_input, expected_label, expected_blocked)
CASES = [
    ("healthy", "Healthy", False),
    ("degraded", "Degraded", False),
    ("unreachable", "Unreachable", True),
    ("unknown", "Unknown", False),
    ("", "Unknown", False),  # empty string → default branch
    ("other", "Unknown", False),  # unknown string → default branch
]


@pytest.fixture(scope="module")
def results():
    if shutil.which("node") is None:
        pytest.skip("node not available")
    if not HELPER.exists():
        pytest.fail(f"{HELPER} does not exist — create frontend/src/lib/saltMasterHelpers.ts")

    statuses = [c[0] for c in CASES]
    proc = subprocess.run(
        [
            "node",
            "--experimental-strip-types",
            "--no-warnings",
            str(HARNESS),
            json.dumps(statuses),
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        timeout=30,
    )
    if proc.returncode != 0:
        pytest.fail(f"harness failed (rc={proc.returncode}):\n{proc.stderr}\n{proc.stdout}")
    return json.loads(proc.stdout)


def test_helper_file_exists():
    assert HELPER.exists(), "frontend/src/lib/saltMasterHelpers.ts must exist"


@pytest.mark.parametrize(
    "idx,status,expected_label,expected_blocked",
    [(i, c[0], c[1], c[2]) for i, c in enumerate(CASES)],
    ids=[c[0] if c[0] else "empty" for c in CASES],
)
def test_salt_master_badge_label(results, idx, status, expected_label, expected_blocked):
    result = results[idx]
    assert result["badge"]["label"] == expected_label, (
        f"saltMasterBadge({status!r}).label: got {result['badge']['label']!r}, want {expected_label!r}"
    )


@pytest.mark.parametrize(
    "idx,status,expected_label,expected_blocked",
    [(i, c[0], c[1], c[2]) for i, c in enumerate(CASES)],
    ids=[c[0] if c[0] else "empty" for c in CASES],
)
def test_is_bootstrap_blocked(results, idx, status, expected_label, expected_blocked):
    result = results[idx]
    assert result["blocked"] == expected_blocked, (
        f"isBootstrapBlocked({status!r}): got {result['blocked']}, want {expected_blocked}"
    )


def test_unreachable_is_the_only_blocked_status(results):
    """Only 'unreachable' must block bootstrap — no other status should."""
    for i, (status, _label, expected_blocked) in enumerate(CASES):
        blocked = results[i]["blocked"]
        if status == "unreachable":
            assert blocked is True, "unreachable must block bootstrap"
        else:
            assert blocked is False, f"status={status!r} must NOT block bootstrap"


def test_badge_has_sufficient_contrast_classes(results):
    """Badge bg+text class pairs must use high-contrast tailwind classes (not gray-400)."""
    low_contrast = {"text-gray-400", "text-gray-300", "text-gray-200"}
    for i, (status, _label, _blocked) in enumerate(CASES):
        badge = results[i]["badge"]
        assert badge["textClass"] not in low_contrast, (
            f"saltMasterBadge({status!r}).textClass={badge['textClass']!r} is too low contrast"
        )
