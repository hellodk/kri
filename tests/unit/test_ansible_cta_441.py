"""#441: Ansible stat card must be clickable and route to Settings → Integrations.

Tests the pure ansibleCardCta helper (frontend/src/lib/ansibleCta.ts) that maps
the configured endpoint URL to the card's status label, hint, and navigation
route. Runs the real TS via node --experimental-strip-types.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
HARNESS = Path(__file__).parent / "_ansible_cta_harness.ts"
HELPER = ROOT / "frontend/src/lib/ansibleCta.ts"

ROUTE = "/settings?tab=Integrations"

# (name, endpoint_url, expected)
CASES = [
    ("null", None, {"status": "Not configured", "hint": "Set in Settings", "route": ROUTE}),
    ("empty", "", {"status": "Not configured", "hint": "Set in Settings", "route": ROUTE}),
    (
        "configured",
        "http://awx.local",
        {"status": "Connected", "hint": "http://awx.local", "route": ROUTE},
    ),
]


@pytest.fixture(scope="module")
def results():
    if shutil.which("node") is None:
        pytest.skip("node not available")
    args = [[c[1]] for c in CASES]
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
    assert HELPER.exists(), "frontend/src/lib/ansibleCta.ts must exist"


@pytest.mark.parametrize("idx", range(len(CASES)), ids=[c[0] for c in CASES])
def test_ansible_cta(results, idx):
    name, _url, expected = CASES[idx]
    assert results[idx] == expected, f"case {name}: got {results[idx]}, want {expected}"


def test_card_is_clickable_in_playbooks_page():
    """The Ansible card must wire the helper's route to a navigate handler."""
    page = (ROOT / "frontend/src/pages/PlaybooksPage.tsx").read_text()
    assert "ansibleCardCta" in page, "PlaybooksPage must use the ansibleCardCta helper"
    # The card must navigate to the helper's route on click (route value itself is
    # asserted by the test_ansible_cta cases above — here we verify the wiring).
    assert "navigate(cta.route)" in page, "Ansible card must navigate to cta.route on click"
