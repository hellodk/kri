"""
Source-contract tests for salt/states/base/harden_compute.sls and
salt/states/base/unharden_compute.sls (GitHub issue #632, Phase 4a of #597).

These tests verify the static content of the Salt state files without
requiring a Salt minion or macOS environment.
"""

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths resolved relative to this test file — never absolute, per project rules
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
_STATES_DIR = _REPO_ROOT / "salt" / "states" / "base"

HARDEN_SLS = _STATES_DIR / "harden_compute.sls"
UNHARDEN_SLS = _STATES_DIR / "unharden_compute.sls"

# Labels that must NEVER appear in harden_compute.sls (case-insensitive)
NEVER_DISABLE = [
    "salt-minion",
    "salt-master",
    "sshd",
    "mDNSResponder",
    "configd",
    "powerd",
    "securityd",
    "trustd",
    "opendirectoryd",
    "syslogd",
    "networkd",
    "exo",
]

# Expected labels that must appear in both files
EXPECTED_LABELS = [
    "com.apple.assistantd",
    "com.apple.Siri.agent",
    "com.apple.siriknowledged",
    "com.apple.parsecd",
    "com.apple.photoanalysisd",
    "com.apple.photolibraryd",
    "com.apple.mediaanalysisd",
    "com.apple.gamed",
    "com.apple.ScreenTimeAgent",
    "com.apple.AirPlayXPCHelper",
    "com.apple.analyticsd",
    "com.apple.osanalytics.osanalyticshelper",
    "com.apple.suggestd",
    "com.apple.knowledgeconstructiond",
    "com.apple.ap.adprivacyd",
]


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_labels(content: str) -> set:
    """Return the set of com.apple.* labels found in the file."""
    return set(re.findall(r"com\.apple\.[a-zA-Z0-9_.]+", content))


# ---------------------------------------------------------------------------
# Existence
# ---------------------------------------------------------------------------


def test_harden_compute_sls_exists():
    assert HARDEN_SLS.exists(), f"Missing: {HARDEN_SLS}"


def test_unharden_compute_sls_exists():
    assert UNHARDEN_SLS.exists(), f"Missing: {UNHARDEN_SLS}"


# ---------------------------------------------------------------------------
# Harden content
# ---------------------------------------------------------------------------


def test_harden_contains_launchctl_disable():
    content = _read(HARDEN_SLS)
    assert "launchctl disable" in content, "harden_compute.sls must contain 'launchctl disable'"


def test_harden_contains_mdutil_off():
    content = _read(HARDEN_SLS)
    assert "mdutil -i off" in content, "harden_compute.sls must contain 'mdutil -i off'"


# ---------------------------------------------------------------------------
# Unharden content
# ---------------------------------------------------------------------------


def test_unharden_contains_launchctl_enable():
    content = _read(UNHARDEN_SLS)
    assert "launchctl enable" in content, "unharden_compute.sls must contain 'launchctl enable'"


def test_unharden_contains_mdutil_on():
    content = _read(UNHARDEN_SLS)
    assert "mdutil -i on" in content, "unharden_compute.sls must contain 'mdutil -i on'"


# ---------------------------------------------------------------------------
# Safety: NEVER-disable tokens must not appear in harden_compute.sls
# ---------------------------------------------------------------------------


def test_harden_excludes_never_disable_tokens():
    # Check only non-comment lines so the NEVER-disable *documentation list* in
    # the header comment doesn't trigger a false positive.
    non_comment_lines = [line for line in _read(HARDEN_SLS).splitlines() if not line.lstrip().startswith("#")]
    content_no_comments = "\n".join(non_comment_lines).lower()
    violations = [token for token in NEVER_DISABLE if token.lower() in content_no_comments]
    assert not violations, f"harden_compute.sls contains forbidden service(s) outside comments: {violations}"


# ---------------------------------------------------------------------------
# Label symmetry: same set of com.apple.* labels in both files
# ---------------------------------------------------------------------------


def test_label_sets_match_between_harden_and_unharden():
    harden_labels = _extract_labels(_read(HARDEN_SLS))
    unharden_labels = _extract_labels(_read(UNHARDEN_SLS))
    only_in_harden = harden_labels - unharden_labels
    only_in_unharden = unharden_labels - harden_labels
    assert not only_in_harden, f"Labels in harden but NOT unharden: {only_in_harden}"
    assert not only_in_unharden, f"Labels in unharden but NOT harden: {only_in_unharden}"


def test_all_expected_labels_present_in_harden():
    content = _read(HARDEN_SLS)
    missing = [label for label in EXPECTED_LABELS if label not in content]
    assert not missing, f"harden_compute.sls is missing expected labels: {missing}"


def test_all_expected_labels_present_in_unharden():
    content = _read(UNHARDEN_SLS)
    missing = [label for label in EXPECTED_LABELS if label not in content]
    assert not missing, f"unharden_compute.sls is missing expected labels: {missing}"


# ---------------------------------------------------------------------------
# Safety documentation: both files must contain the validation warning
# ---------------------------------------------------------------------------


def test_harden_contains_validate_warning():
    content = _read(HARDEN_SLS)
    assert "VALIDATE" in content, "harden_compute.sls must contain 'VALIDATE' in a comment"
    assert "test mini" in content.lower() or "test Mini" in content, (
        "harden_compute.sls must contain 'test mini' or 'test Mini' in a comment"
    )


def test_unharden_contains_validate_warning():
    content = _read(UNHARDEN_SLS)
    assert "VALIDATE" in content, "unharden_compute.sls must contain 'VALIDATE' in a comment"
    assert "test mini" in content.lower() or "test Mini" in content, (
        "unharden_compute.sls must contain 'test mini' or 'test Mini' in a comment"
    )


# ---------------------------------------------------------------------------
# Fail-tolerance: every launchctl command must have "|| true"
# ---------------------------------------------------------------------------


def test_harden_launchctl_commands_are_fail_tolerant():
    content = _read(HARDEN_SLS)
    # Only check lines that are actual shell commands (contain - name:) not
    # onlyif: guards or comments — the onlyif expression legitimately uses
    # launchctl as a guard without needing || true.
    cmd_lines = [
        line.strip()
        for line in content.splitlines()
        if "launchctl" in line and not line.strip().startswith("#") and "- name:" in line
    ]
    non_tolerant = [line for line in cmd_lines if "|| true" not in line]
    assert not non_tolerant, f"harden_compute.sls has launchctl command lines without '|| true': {non_tolerant}"


def test_unharden_launchctl_commands_are_fail_tolerant():
    content = _read(UNHARDEN_SLS)
    cmd_lines = [
        line.strip()
        for line in content.splitlines()
        if "launchctl" in line and not line.strip().startswith("#") and "- name:" in line
    ]
    non_tolerant = [line for line in cmd_lines if "|| true" not in line]
    assert not non_tolerant, f"unharden_compute.sls has launchctl command lines without '|| true': {non_tolerant}"


# ---------------------------------------------------------------------------
# Unique state IDs: no duplicate IDs within each file
# ---------------------------------------------------------------------------


def test_harden_state_ids_are_unique():
    content = _read(HARDEN_SLS)
    # State IDs are lines that start at column 0, end with ':', and are not comments
    ids = [
        line.rstrip(":")
        for line in content.splitlines()
        if line
        and not line.startswith(" ")
        and not line.startswith("#")
        and not line.startswith("{")
        and not line.startswith("%")
        and line.endswith(":")
    ]
    assert len(ids) == len(set(ids)), f"Duplicate state IDs in harden_compute.sls: {ids}"


def test_unharden_state_ids_are_unique():
    content = _read(UNHARDEN_SLS)
    ids = [
        line.rstrip(":")
        for line in content.splitlines()
        if line
        and not line.startswith(" ")
        and not line.startswith("#")
        and not line.startswith("{")
        and not line.startswith("%")
        and line.endswith(":")
    ]
    assert len(ids) == len(set(ids)), f"Duplicate state IDs in unharden_compute.sls: {ids}"
