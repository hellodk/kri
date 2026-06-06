"""
Tests for issue #391: Merge Bootstrap + Advanced tabs into Automation tab.

Source-contract style: these tests parse the frontend TypeScript source file
directly and assert on its content.
"""

import re
from pathlib import Path

SETTINGS_PAGE = Path(__file__).parent.parent.parent / "frontend" / "src" / "pages" / "SettingsPage.tsx"

_SOURCE = SETTINGS_PAGE.read_text()


# ---------------------------------------------------------------------------
# 1. TABS literal matches AC exactly
# ---------------------------------------------------------------------------


def test_tabs_literal_matches_ac():
    """TABS must be exactly the array defined in AC1, in that order."""
    pattern = re.compile(
        r"const TABS\s*=\s*\["
        r"['\"]General['\"],\s*"
        r"['\"]Automation['\"],\s*"
        r"['\"]Remote Access['\"],\s*"
        r"['\"]Integrations['\"],\s*"
        r"['\"]Playbook Library['\"],\s*"
        r"['\"]LLM['\"],\s*"
        r"['\"]Notifications['\"]"
        r"\]\s*as\s+const"
    )
    assert pattern.search(_SOURCE), (
        "TABS literal does not match expected order. "
        "Expected: ['General', 'Automation', 'Remote Access', 'Integrations', "
        "'Playbook Library', 'LLM', 'Notifications']"
    )


def test_bootstrap_tab_absent_from_tabs_literal():
    """'Bootstrap' must not appear inside the TABS array literal."""
    # Extract the TABS literal line only
    m = re.search(r"const TABS\s*=\s*\[(.+?)\]\s*as\s+const", _SOURCE)
    assert m, "Could not find TABS literal"
    tabs_content = m.group(1)
    assert "Bootstrap" not in tabs_content, "'Bootstrap' still present inside TABS array"


def test_advanced_tab_absent_from_tabs_literal():
    """'Advanced' must not appear inside the TABS array literal."""
    m = re.search(r"const TABS\s*=\s*\[(.+?)\]\s*as\s+const", _SOURCE)
    assert m, "Could not find TABS literal"
    tabs_content = m.group(1)
    assert "Advanced" not in tabs_content, "'Advanced' still present inside TABS array"


# ---------------------------------------------------------------------------
# 2. No remaining activeTab comparisons against removed tab names
# ---------------------------------------------------------------------------


def test_no_active_tab_bootstrap_comparison():
    """No activeTab === 'Bootstrap' (or 'Bootstrap' === activeTab) anywhere."""
    pattern = re.compile(r"activeTab\s*===\s*['\"]Bootstrap['\"]|['\"]Bootstrap['\"]\s*===\s*activeTab")
    matches = pattern.findall(_SOURCE)
    assert not matches, f"Found {len(matches)} activeTab comparison(s) to 'Bootstrap': {matches}"


def test_no_active_tab_advanced_comparison():
    """No activeTab === 'Advanced' (or 'Advanced' === activeTab) anywhere."""
    pattern = re.compile(r"activeTab\s*===\s*['\"]Advanced['\"]|['\"]Advanced['\"]\s*===\s*activeTab")
    matches = pattern.findall(_SOURCE)
    assert not matches, f"Found {len(matches)} activeTab comparison(s) to 'Advanced': {matches}"


# ---------------------------------------------------------------------------
# 3. Automation tab block: correct source order of sections
# ---------------------------------------------------------------------------


def _find_automation_block(source: str) -> str:
    """
    Extract the JSX block for the Automation tab.
    Looks for the comment/conditional that opens the Automation tab and
    returns everything up to the next tab comment block.
    """
    # Find the start of the Automation tab block
    start_pattern = re.compile(r"activeTab\s*===\s*['\"]Automation['\"]")
    m = start_pattern.search(source)
    assert m, "Could not find 'activeTab === Automation' in source"
    start = m.start()

    # Find the next tab block after Automation (Remote Access)
    next_tab_pattern = re.compile(r"activeTab\s*===\s*['\"]Remote Access['\"]")
    m2 = next_tab_pattern.search(source, start + 1)
    end = m2.start() if m2 else len(source)

    return source[start:end]


def test_automation_block_contains_credentials_first():
    """Automation block must reference CredentialsSection first."""
    block = _find_automation_block(_SOURCE)
    assert "CredentialsSection" in block, "CredentialsSection not found in Automation tab block"


def test_automation_block_contains_ssh_bootstrap():
    """Automation block must contain Default SSH Bootstrap Credentials section."""
    block = _find_automation_block(_SOURCE)
    assert "Default SSH Bootstrap Credentials" in block, (
        "'Default SSH Bootstrap Credentials' heading not found in Automation tab block"
    )


def test_automation_block_contains_allowlist():
    """Automation block must reference SaltAllowlistSection / SaltDenylistSection."""
    block = _find_automation_block(_SOURCE)
    assert "SaltAllowlistSection" in block or "Salt Function Allowlist" in block, (
        "Salt allowlist not found in Automation tab block"
    )


def test_automation_block_contains_playbook_sources():
    """Automation block must reference PlaybookSourcesSection."""
    block = _find_automation_block(_SOURCE)
    assert "PlaybookSourcesSection" in block, "PlaybookSourcesSection not found in Automation tab block"


def test_automation_sections_order():
    """
    Verify source order: Credentials → SSH Bootstrap → Allowlist → Playbook Sources.
    Uses character position within the Automation block.
    """
    block = _find_automation_block(_SOURCE)

    pos_credentials = block.find("CredentialsSection")
    pos_bootstrap = block.find("Default SSH Bootstrap Credentials")
    pos_allowlist = max(
        block.find("SaltAllowlistSection"),
        block.find("Salt Function Allowlist"),
    )
    pos_playbook = block.find("PlaybookSourcesSection")

    assert pos_credentials != -1, "CredentialsSection marker missing"
    assert pos_bootstrap != -1, "Default SSH Bootstrap Credentials marker missing"
    assert pos_allowlist != -1, "Salt allowlist marker missing"
    assert pos_playbook != -1, "PlaybookSourcesSection marker missing"

    assert pos_credentials < pos_bootstrap, (
        "Credentials must appear before Default SSH Bootstrap in the Automation block"
    )
    assert pos_bootstrap < pos_allowlist, (
        "Default SSH Bootstrap must appear before Salt Allowlist in the Automation block"
    )
    assert pos_allowlist < pos_playbook, "Salt Allowlist must appear before Playbook Sources in the Automation block"


# ---------------------------------------------------------------------------
# 4. Legacy mapping Bootstrap / Advanced → Automation
# ---------------------------------------------------------------------------


def test_legacy_mapping_present():
    """
    A mapping from legacy tab values ('Bootstrap', 'Advanced') to 'Automation'
    must exist in the source (e.g. via a useState initialiser guard or URL-param
    normaliser).
    """
    # At minimum, both removed names and the new name must co-exist in a small window
    # (within 500 chars of each other) — indicating a mapping construct
    bootstrap_positions = [m.start() for m in re.finditer(r"['\"]Bootstrap['\"]", _SOURCE)]
    automation_positions = [m.start() for m in re.finditer(r"['\"]Automation['\"]", _SOURCE)]

    found_close = any(abs(b - a) < 600 for b in bootstrap_positions for a in automation_positions)
    assert found_close, (
        "No legacy mapping found: 'Bootstrap' and 'Automation' never appear within "
        "600 characters of each other. Add a legacy → Automation mapping for stored/URL tab values."
    )
