"""Issue #589: move Salt Masters from Settings into the Overview hub.

Source-contract style: parse the frontend TypeScript/TSX sources directly and
assert on their content. Salt Masters is provisioning/lifecycle (operational),
so it belongs in the Overview hub, not in Settings configuration.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent / "frontend" / "src"

OVERVIEW_HUB = ROOT / "pages" / "OverviewHub.tsx"
SETTINGS_PAGE = ROOT / "pages" / "SettingsPage.tsx"
TAB_PARAM = ROOT / "lib" / "settingsTabParam.ts"
DASHBOARD = ROOT / "pages" / "DashboardPage.tsx"
FLEET_DASHBOARD = ROOT / "pages" / "FleetDashboard.tsx"


# ---------------------------------------------------------------------------
# 1. Overview hub gains the Salt Masters tab
# ---------------------------------------------------------------------------


def test_overview_hub_imports_salt_masters_tab():
    src = OVERVIEW_HUB.read_text()
    assert "SaltMastersTab" in src, "OverviewHub must import SaltMastersTab"


def test_overview_hub_registers_salt_masters_tab():
    """A HubTab with key 'salt-masters' bound to the SaltMastersTab component."""
    src = OVERVIEW_HUB.read_text()
    pattern = re.compile(
        r"key:\s*['\"]salt-masters['\"][^}]*component:\s*SaltMastersTab",
        re.DOTALL,
    )
    assert pattern.search(src), (
        "OverviewHub TABS must contain a tab { key: 'salt-masters', ..., component: SaltMastersTab }"
    )


# ---------------------------------------------------------------------------
# 2. Settings loses the Salt Masters tab
# ---------------------------------------------------------------------------


def test_settings_tabs_literal_excludes_salt_masters():
    src = SETTINGS_PAGE.read_text()
    m = re.search(r"const TABS\s*=\s*\[(.+?)\]\s*as\s+const", src, re.DOTALL)
    assert m, "Could not find TABS literal in SettingsPage"
    assert "Salt Masters" not in m.group(1), "'Salt Masters' must be removed from the Settings TABS literal"


def test_settings_no_longer_renders_salt_masters_tab():
    src = SETTINGS_PAGE.read_text()
    assert "<SaltMastersTab" not in src, "SettingsPage must not render <SaltMastersTab />"
    assert not re.search(r"activeTab\s*===\s*['\"]Salt Masters['\"]", src), (
        "SettingsPage must not retain an activeTab === 'Salt Masters' branch"
    )


def test_settings_tab_param_excludes_salt_masters():
    src = TAB_PARAM.read_text()
    m = re.search(r"SETTINGS_TABS\s*=\s*\[(.+?)\]\s*as\s+const", src, re.DOTALL)
    assert m, "Could not find SETTINGS_TABS literal"
    assert "Salt Masters" not in m.group(1), "'Salt Masters' must be removed from SETTINGS_TABS"


# ---------------------------------------------------------------------------
# 3. Legacy deep-link redirect
# ---------------------------------------------------------------------------


def test_settings_redirects_legacy_salt_masters_link():
    """SettingsPage must redirect ?tab=Salt Masters → /overview?tab=salt-masters."""
    src = SETTINGS_PAGE.read_text()
    assert "/overview?tab=salt-masters" in src, (
        "SettingsPage must redirect the legacy 'Salt Masters' tab to /overview?tab=salt-masters"
    )
    # the redirect must be keyed off the legacy value
    salt_pos = [m.start() for m in re.finditer(r"['\"]Salt Masters['\"]", src)]
    redir_pos = [m.start() for m in re.finditer(r"/overview\?tab=salt-masters", src)]
    assert any(abs(s - r) < 400 for s in salt_pos for r in redir_pos), (
        "Legacy 'Salt Masters' value and the /overview?tab=salt-masters redirect must appear together"
    )


# ---------------------------------------------------------------------------
# 4. In-app links updated
# ---------------------------------------------------------------------------


def test_no_settings_salt_masters_links_remain():
    for path in (DASHBOARD, FLEET_DASHBOARD):
        src = path.read_text()
        assert 'tab=Salt Masters"' not in src and "tab=Salt Masters'" not in src, (
            f"{path.name} still links to /settings?tab=Salt Masters — must point to /overview?tab=salt-masters"
        )
