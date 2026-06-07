"""Guard tests for issue #581 — IST timestamps, WCAG contrast, a11y."""

import re
from pathlib import Path

FRONTEND_PAGES = Path("frontend/src/pages")

# Files touched by this fix
TOUCHED_PAGES = [
    "NodeDetail.tsx",
    "FleetHealthPage.tsx",
    "ExecutionHistory.tsx",
    "PlaybookJobDetail.tsx",
    "DashboardPage.tsx",
    "SettingsPage.tsx",
    "SaltMastersTab.tsx",
]


def _read(name: str) -> str:
    return (FRONTEND_PAGES / name).read_text()


# ── IST violations ────────────────────────────────────────────────────────────


def test_node_detail_secret_no_raw_tolocalestring():
    """NodeDetail secret 'last updated' must use formatIST, not raw toLocaleString."""
    content = _read("NodeDetail.tsx")
    # The old pattern was new Date(s.updated_at).toLocaleString()
    assert "new Date(s.updated_at).toLocaleString()" not in content, (
        "NodeDetail.tsx still uses raw toLocaleString() for secret updated_at — use formatIST()"
    )


def test_fleet_health_no_bare_date_fns_format():
    """FleetHealthPage must not use bare date-fns format() for timestamps."""
    content = _read("FleetHealthPage.tsx")
    # Must not import `format` from date-fns (we replaced it with formatIST/formatChartDate)
    bare_format_import = re.search(r"import\s*\{[^}]*\bformat\b[^}]*\}\s*from\s*['\"]date-fns['\"]", content)
    assert bare_format_import is None, (
        "FleetHealthPage.tsx still imports bare `format` from date-fns — use formatIST/formatChartDate"
    )


def test_fleet_health_uses_ist_utils():
    """FleetHealthPage must use the IST util for snapshot display."""
    content = _read("FleetHealthPage.tsx")
    assert "formatIST" in content or "formatChartDate" in content, (
        "FleetHealthPage.tsx must use formatIST or formatChartDate from utils/time"
    )


def test_execution_history_started_at_has_ist_title():
    """ExecutionHistory started_at relative times must have an absolute IST title attribute."""
    content = _read("ExecutionHistory.tsx")
    assert "formatIST" in content, "ExecutionHistory.tsx must import and use formatIST for title tooltips on started_at"
    # Must have a title prop near formatDistanceToNow calls
    assert "title={" in content and "formatIST" in content, (
        "ExecutionHistory.tsx: formatDistanceToNow blocks must have a formatIST title tooltip"
    )


def test_playbook_job_detail_started_at_has_ist_title():
    """PlaybookJobDetail started_at relative time must have an absolute IST title."""
    content = _read("PlaybookJobDetail.tsx")
    assert "formatIST" in content, "PlaybookJobDetail.tsx must use formatIST for the started_at title tooltip"
    assert "title={formatIST(" in content, (
        "PlaybookJobDetail.tsx: started_at <p> must have title={formatIST(job.started_at)}"
    )


# ── WCAG contrast — no meaningful text-gray-400 on white ─────────────────────

_MEANINGFUL_GRAY400_PATTERN = re.compile(r'className=["\'][^"\']*\btext-gray-400\b[^"\']*["\']')

_MEANINGFUL_CONTEXTS = [
    # Empty-state messages: p/td/div using text-gray-400 as the *light-mode* color.
    # Exclude dark:text-gray-400 (which is only the dark-mode variant, fine on dark bg).
    # A className is a problem only when text-gray-400 is NOT preceded by dark:
    (r"<p\b[^>]*(?<!dark:)\btext-gray-400\b", "empty-state <p> with (light-mode) text-gray-400"),
    (r"<td\b[^>]*(?<!dark:)\btext-gray-400\b[^>]*>[^<]{3}", "non-empty <td> with text-gray-400"),
    (
        r"<div\b[^>]*(?<!dark:)\btext-gray-400\b[^>]*>(?:\s*\n\s*)?(?:No |Loading )",
        "empty-state <div> with text-gray-400",
    ),
]


def test_node_detail_no_meaningful_gray400():
    """NodeDetail.tsx: meaningful text must not use text-gray-400 (fails WCAG 4.5:1)."""
    content = _read("NodeDetail.tsx")
    for pattern, label in _MEANINGFUL_CONTEXTS:
        hits = re.findall(pattern, content)
        assert len(hits) == 0, (
            f"NodeDetail.tsx: found {label} — bump to text-gray-600 (text) or text-gray-500 (icons):\n"
            + "\n".join(hits[:5])
        )


def test_dashboard_no_meaningful_gray400():
    """DashboardPage.tsx: meaningful text must not use text-gray-400."""
    content = _read("DashboardPage.tsx")
    # "No recent node activity" empty state
    assert 'text-gray-400">\\n              No recent node activity' not in content, (
        "DashboardPage.tsx still has 'No recent node activity' in text-gray-400"
    )
    for pattern, label in _MEANINGFUL_CONTEXTS:
        hits = re.findall(pattern, content)
        assert len(hits) == 0, f"DashboardPage.tsx: found {label} — bump to text-gray-600:\n" + "\n".join(hits[:5])


def test_settings_oidc_cta_not_gray400():
    """SettingsPage OIDC CTA text must not be text-gray-400."""
    content = _read("SettingsPage.tsx")
    assert 'text-gray-400">Enable OIDC' not in content, (
        "SettingsPage.tsx: OIDC CTA text is still text-gray-400 — use text-gray-600"
    )


# ── a11y ──────────────────────────────────────────────────────────────────────


def test_salt_masters_loading_has_role_status():
    """SaltMastersTab 'Loading minions…' region must have role='status' and aria-live."""
    content = _read("SaltMastersTab.tsx")
    assert 'role="status"' in content, "SaltMastersTab.tsx: 'Loading minions…' region missing role=\"status\""
    assert "aria-live=" in content, "SaltMastersTab.tsx: 'Loading minions…' region missing aria-live attribute"


def test_salt_masters_close_button_has_aria_label():
    """SaltMastersTab close × button must have aria-label."""
    content = _read("SaltMastersTab.tsx")
    # The modal close button should have aria-label="Close"
    assert 'aria-label="Close"' in content, 'SaltMastersTab.tsx: close × button missing aria-label="Close"'
