"""Source-contract test: PROTECTED_TARGETS in the NodeDetail utils module must
stay in sync with PendingAction.PROTECTED_TARGETS in
fleet_platform/models/pending_action.py.

Issue #629 — Phase 3 of #597.

The frontend constant moved from NodeDetail.tsx into
frontend/src/pages/nodeDetail/utils.ts during the NodeDetail extraction
(#arch-nodedetail). Both the helper-presence checks and the disabled-button
checks still live in NodeDetail.tsx because they describe page-level wiring.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_FILE = ROOT / "fleet_platform" / "models" / "pending_action.py"
NODE_DETAIL_TSX = ROOT / "frontend" / "src" / "pages" / "NodeDetail.tsx"
NODE_DETAIL_UTILS = ROOT / "frontend" / "src" / "pages" / "nodeDetail" / "utils.ts"


def _parse_backend_targets() -> set[str]:
    """Extract the string literals inside PROTECTED_TARGETS = frozenset({...})."""
    src = BACKEND_FILE.read_text()
    # Match the entire frozenset block
    m = re.search(r"PROTECTED_TARGETS\s*=\s*frozenset\(\s*\{([^}]+)\}", src, re.DOTALL)
    assert m, f"Could not find PROTECTED_TARGETS frozenset in {BACKEND_FILE}"
    body = m.group(1)
    # Extract all quoted string literals
    return set(re.findall(r'"([^"]+)"', body)) | set(re.findall(r"'([^']+)'", body))


def _parse_frontend_targets() -> set[str]:
    """Extract the string literals inside PROTECTED_TARGETS = new Set([...])."""
    src = NODE_DETAIL_UTILS.read_text()
    # Match the entire Set block
    m = re.search(r"PROTECTED_TARGETS\s*=\s*new\s+Set\(\s*\[([^\]]+)\]", src, re.DOTALL)
    assert m, f"Could not find PROTECTED_TARGETS Set in {NODE_DETAIL_UTILS}"
    body = m.group(1)
    # Extract all quoted string literals (single or double)
    return set(re.findall(r'"([^"]+)"', body)) | set(re.findall(r"'([^']+)'", body))


def test_protected_targets_in_sync():
    """Backend frozenset and frontend Set must contain exactly the same entries."""
    backend = _parse_backend_targets()
    frontend = _parse_frontend_targets()
    assert backend, "Backend PROTECTED_TARGETS must not be empty"
    assert frontend, "Frontend PROTECTED_TARGETS must not be empty"
    assert backend == frontend, (
        f"PROTECTED_TARGETS drift detected!\n"
        f"  In backend only:  {backend - frontend}\n"
        f"  In frontend only: {frontend - backend}\n"
        f"Update {NODE_DETAIL_UTILS.name} to match fleet_platform/models/pending_action.py"
    )


def test_frontend_has_is_protected_target_helper():
    """The shared utils module must define the isProtectedTarget helper function."""
    src = NODE_DETAIL_UTILS.read_text()
    assert "isProtectedTarget(" in src, (
        f"{NODE_DETAIL_UTILS.name} must contain the isProtectedTarget() helper function"
    )


def test_frontend_has_service_enable_action():
    """NodeDetail.tsx must include 'service_enable' action type."""
    src = NODE_DETAIL_TSX.read_text()
    assert "'service_enable'" in src, "NodeDetail.tsx must contain 'service_enable' action type for the Enable button"


def test_frontend_has_disabled_prot_attribute():
    """NodeDetail.tsx must contain disabled={prot} at least twice (services + processes tabs)."""
    src = NODE_DETAIL_TSX.read_text()
    occurrences = src.count("disabled={prot}")
    assert occurrences >= 2, (
        f"Expected at least 2 occurrences of disabled={{prot}} in NodeDetail.tsx, "
        f"found {occurrences}. Both the Services and Processes tabs must disable "
        "protected-target buttons."
    )
