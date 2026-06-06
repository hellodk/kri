"""Tests for #373: pure isAtBottom helper (frontend/src/lib/scrollFollow.ts).

Runs the real TS via node --experimental-strip-types — the threshold math is the
bug-prone part the fix hinges on, so it is tested behaviorally.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
HARNESS = Path(__file__).parent / "_scroll_harness.ts"
HELPER = ROOT / "frontend/src/lib/scrollFollow.ts"

# (name, [scrollHeight, scrollTop, clientHeight, (threshold?)], expected)
CASES = [
    ("at_bottom", [1000, 900, 100], True),  # 0 < 40
    ("within_threshold", [1000, 870, 100], True),  # 30 < 40
    ("beyond_threshold", [1000, 850, 100], False),  # 50 < 40 -> false
    ("at_top", [1000, 0, 100], False),  # 900 < 40 -> false
    ("non_scrollable", [100, 0, 100], True),  # 0 < 40
    ("exact_boundary", [1000, 860, 100], False),  # 40 < 40 -> false (strict)
    ("custom_threshold_within", [1000, 850, 100, 120], True),  # 50 < 120
    ("custom_threshold_beyond", [1000, 850, 100, 30], False),  # 50 < 30 -> false
]


@pytest.fixture(scope="module")
def results():
    if shutil.which("node") is None:
        pytest.skip("node not available")
    args = [c[1] for c in CASES]
    proc = subprocess.run(
        ["node", "--experimental-strip-types", "--no-warnings", str(HARNESS), json.dumps(args)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        timeout=30,
    )
    if proc.returncode != 0:
        pytest.fail(f"harness failed (rc={proc.returncode}):\n{proc.stderr}")
    return json.loads(proc.stdout)


def test_helper_exists():
    assert HELPER.exists(), "frontend/src/lib/scrollFollow.ts must exist"


@pytest.mark.parametrize("idx", range(len(CASES)), ids=[c[0] for c in CASES])
def test_is_at_bottom(results, idx):
    name, _args, expected = CASES[idx]
    assert results[idx] == expected, f"case {name}: got {results[idx]}, want {expected}"
