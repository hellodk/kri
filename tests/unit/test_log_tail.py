"""Tests for #370: pure tailLines helper (frontend/src/lib/tailLines.ts).

Runs the real TS via node --experimental-strip-types — the tail-cap logic
is the core fix, so it is tested behaviorally with real output boundaries.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
HARNESS = Path(__file__).parent / "_tail_harness.ts"
HELPER = ROOT / "frontend/src/lib/tailLines.ts"

# (name, [raw, max?], expected_result)
CASES = [
    ("empty_string", ["", None], {"text": "", "hiddenLines": 0}),
    ("three_lines_max_five", ["l0\nl1\nl2", 5], {"text": "l0\nl1\nl2", "hiddenLines": 0}),
    ("exact_five_lines", ["l0\nl1\nl2\nl3\nl4", 5], {"text": "l0\nl1\nl2\nl3\nl4", "hiddenLines": 0}),
    ("eight_lines_max_five", ["l0\nl1\nl2\nl3\nl4\nl5\nl6\nl7", 5], {"text": "l3\nl4\nl5\nl6\nl7", "hiddenLines": 3}),
    (
        "default_max_500",
        ["\n".join(f"l{i}" for i in range(501)), None],
        {"text": "\n".join(f"l{i}" for i in range(1, 501)), "hiddenLines": 1},
    ),
    ("ansi_codes_preserved", ["a\n\x1b[32mok\x1b[0m\nb", 2], {"text": "\x1b[32mok\x1b[0m\nb", "hiddenLines": 1}),
]


@pytest.fixture(scope="module")
def results():
    if shutil.which("node") is None:
        pytest.skip("node not available")
    # Prepare args, filtering out None max values to keep them as single-element arrays
    args = []
    for case in CASES:
        if case[1][1] is None:
            args.append([case[1][0]])
        else:
            args.append(list(case[1]))

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
    assert HELPER.exists(), "frontend/src/lib/tailLines.ts must exist"


@pytest.mark.parametrize("idx", range(len(CASES)), ids=[c[0] for c in CASES])
def test_tail_lines(results, idx):
    name, _args, expected = CASES[idx]
    result = results[idx]
    assert result == expected, f"case {name}: got {result}, want {expected}"
