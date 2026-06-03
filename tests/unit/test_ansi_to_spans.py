"""Tests for #369: ANSI SGR -> AnsiSpan[] parser (frontend/src/lib/ansiToSpans.ts).

Runs the actual TypeScript parser via `node --experimental-strip-types` so the test
exercises shipped code, not a Python re-implementation. No JS test runner needed.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
HARNESS = Path(__file__).parent / "_ansi_harness.ts"
PARSER = ROOT / "frontend/src/lib/ansiToSpans.ts"

ESC = "\x1b"

# (name, input, expected spans)
CASES = [
    ("bare_text", "ok: [mm]", [{"text": "ok: [mm]"}]),
    ("single_colour_reset", f"{ESC}[32mok{ESC}[0m", [{"text": "ok", "color": "#4ADE80"}]),
    ("bold_only", f"{ESC}[1mtask{ESC}[0m", [{"text": "task", "bold": True}]),
    ("bold_plus_colour", f"{ESC}[1;32mPLAY{ESC}[0m", [{"text": "PLAY", "color": "#4ADE80", "bold": True}]),
    ("stacked_second_wins", f"{ESC}[32m{ESC}[33mchanged{ESC}[0m", [{"text": "changed", "color": "#FCD34D"}]),
    ("reset_mid_line", f"{ESC}[31mfail{ESC}[0m plain",
     [{"text": "fail", "color": "#F87171"}, {"text": " plain"}]),
    ("unterminated", f"{ESC}[32mok: [mm]", [{"text": "ok: [mm]", "color": "#4ADE80"}]),
    ("empty", "", []),
    ("legacy_plain", "PLAY [all] ***", [{"text": "PLAY [all] ***"}]),
    ("real_ok_line", f"{ESC}[0;32mok: [mm]{ESC}[0m", [{"text": "ok: [mm]", "color": "#4ADE80"}]),
    ("real_changed_line", f"{ESC}[0;33mchanged: [host]{ESC}[0m",
     [{"text": "changed: [host]", "color": "#FCD34D"}]),
    ("bright_equals_normal", f"{ESC}[92mok{ESC}[0m", [{"text": "ok", "color": "#4ADE80"}]),
    ("multi_line", f"line1\n{ESC}[32mline2{ESC}[0m",
     [{"text": "line1\n"}, {"text": "line2", "color": "#4ADE80"}]),
    ("unknown_sgr_dropped", f"{ESC}[4mtext{ESC}[0m", [{"text": "text"}]),
    ("malformed_no_m", f"{ESC}[32text", [{"text": f"{ESC}[32text"}]),
    ("lone_cr_normalised", "a\r\nb\rc", [{"text": "a\nbc"}]),
]


@pytest.fixture(scope="module")
def parsed():
    if shutil.which("node") is None:
        pytest.skip("node not available")
    inputs = [c[1] for c in CASES]
    proc = subprocess.run(
        ["node", "--experimental-strip-types", "--no-warnings", str(HARNESS), json.dumps(inputs)],
        capture_output=True, text=True, cwd=str(ROOT), timeout=30,
    )
    if proc.returncode != 0:
        pytest.fail(f"harness failed (rc={proc.returncode}):\n{proc.stderr}")
    return json.loads(proc.stdout)


def test_parser_module_exists():
    assert PARSER.exists(), "frontend/src/lib/ansiToSpans.ts must exist"


@pytest.mark.parametrize("idx", range(len(CASES)), ids=[c[0] for c in CASES])
def test_ansi_case(parsed, idx):
    name, _input, expected = CASES[idx]
    assert parsed[idx] == expected, f"case {name}: got {parsed[idx]}, want {expected}"
