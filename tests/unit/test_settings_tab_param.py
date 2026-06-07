"""Tests for #479: resolveSettingsTab pure helper (frontend/src/lib/settingsTabParam.ts).

Runs the real TS via node --experimental-strip-types — the param→tab resolution
logic is pure, so it is fully testable without a browser or React.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
HARNESS = Path(__file__).parent / "_settings_tab_harness.ts"
HELPER = ROOT / "frontend/src/lib/settingsTabParam.ts"

# (test_id, raw_param_value, expected_tab)
CASES = [
    # Valid tabs pass through unchanged
    ("general_explicit", "General", "General"),
    ("integrations", "Integrations", "Integrations"),
    ("automation", "Automation", "Automation"),
    ("remote_access", "Remote Access", "Remote Access"),
    ("salt_masters", "Salt Masters", "Salt Masters"),
    ("playbook_library", "Playbook Library", "Playbook Library"),
    ("llm", "LLM", "LLM"),
    ("notifications", "Notifications", "Notifications"),
    # Legacy aliases map to Automation
    ("legacy_bootstrap", "Bootstrap", "Automation"),
    ("legacy_advanced", "Advanced", "Automation"),
    # Unknown / empty values fall back to General
    ("unknown_tab", "NonExistent", "General"),
    ("empty_string", "", "General"),
    ("null_value", None, "General"),
]


@pytest.fixture(scope="module")
def results():
    if shutil.which("node") is None:
        pytest.skip("node not available")
    inputs = [c[1] for c in CASES]
    proc = subprocess.run(
        ["node", "--experimental-strip-types", "--no-warnings", str(HARNESS), json.dumps(inputs)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        timeout=30,
    )
    if proc.returncode != 0:
        pytest.fail(f"harness failed (rc={proc.returncode}):\n{proc.stderr}")
    return json.loads(proc.stdout)


def test_helper_exists():
    assert HELPER.exists(), "frontend/src/lib/settingsTabParam.ts must exist"


@pytest.mark.parametrize("idx", range(len(CASES)), ids=[c[0] for c in CASES])
def test_resolve_settings_tab(results, idx):
    test_id, _raw, expected = CASES[idx]
    result = results[idx]
    assert result == expected, f"case {test_id}: got {result!r}, want {expected!r}"
