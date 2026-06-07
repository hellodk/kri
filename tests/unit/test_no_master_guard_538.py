"""Tests for frontend/src/lib/saltMasterGuard.ts — issue #538, epic #537.

Tests the pure helper function:
- fleetActionsBlocked(masters: {enabled:boolean}[] | undefined) → boolean

Rules:
- undefined (loading)      → false  (no flash during initial load)
- []        (none at all)  → true   (zero enabled → blocked)
- [{enabled:false}]        → true   (all disabled → blocked)
- [{enabled:true}]         → false  (at least one enabled → allowed)
- [{enabled:true},{enabled:false}] → false (mixed → at least one active)

Runs the real TypeScript via node --experimental-strip-types.
No mocks — tests the actual implementation.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
HARNESS = Path(__file__).parent / "_no_master_guard_harness.ts"
HELPER = ROOT / "frontend/src/lib/saltMasterGuard.ts"

# (input_json_serialisable, expected_blocked)
# None encodes as null in JSON; the harness maps null → undefined
CASES = [
    # (masters_input, expected_blocked, description)
    (None, False, "undefined/loading → not blocked"),
    ([], True, "empty list → blocked"),
    ([{"enabled": False}], True, "all disabled → blocked"),
    ([{"enabled": True}], False, "one enabled → not blocked"),
    ([{"enabled": True}, {"enabled": False}], False, "mixed → not blocked"),
    ([{"enabled": False}, {"enabled": False}], True, "all disabled multi → blocked"),
]


@pytest.fixture(scope="module")
def results():
    if shutil.which("node") is None:
        pytest.skip("node not available")
    if not HELPER.exists():
        pytest.fail(f"{HELPER} does not exist — create frontend/src/lib/saltMasterGuard.ts")

    inputs = [c[0] for c in CASES]
    proc = subprocess.run(
        [
            "node",
            "--experimental-strip-types",
            "--no-warnings",
            str(HARNESS),
            json.dumps(inputs),
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
    assert HELPER.exists(), "frontend/src/lib/saltMasterGuard.ts must exist"


def test_harness_file_exists():
    assert HARNESS.exists(), "_no_master_guard_harness.ts must exist"


@pytest.mark.parametrize(
    "idx,masters,expected,description",
    [(i, c[0], c[1], c[2]) for i, c in enumerate(CASES)],
    ids=[c[2] for c in CASES],
)
def test_fleet_actions_blocked(results, idx, masters, expected, description):
    result = results[idx]
    assert result["blocked"] == expected, (
        f"fleetActionsBlocked({masters!r}): got {result['blocked']}, want {expected} ({description})"
    )


def test_undefined_never_blocks(results):
    """undefined (None → null → undefined) must never block to avoid a load-flash."""
    idx = next(i for i, c in enumerate(CASES) if c[0] is None)
    assert results[idx]["blocked"] is False, "undefined masters must not block"


def test_empty_list_blocks(results):
    """Empty list (zero masters at all) must block fleet actions."""
    idx = next(i for i, c in enumerate(CASES) if c[0] == [])
    assert results[idx]["blocked"] is True, "empty masters list must block"


def test_one_enabled_is_sufficient(results):
    """A single enabled master is sufficient to unblock fleet actions."""
    idx = next(i for i, c in enumerate(CASES) if c[0] == [{"enabled": True}])
    assert results[idx]["blocked"] is False, "one enabled master must unblock"
