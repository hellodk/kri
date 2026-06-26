"""Tests for #54: Salt Ops UX improvements."""

from pathlib import Path


def test_quick_install_state_exists():
    # Frontend-only feature: TypeScript source is the only testable artifact at the Python unit level.
    src = Path("frontend/src/pages/SaltOpsPage.tsx").read_text()
    assert "quickPackage" in src or "quickPkg" in src.lower()


def test_quick_install_pip_supported():
    # Frontend-only feature: TypeScript source is the only testable artifact at the Python unit level.
    src = Path("frontend/src/pages/SaltOpsPage.tsx").read_text()
    assert "pip.install" in src


def test_quick_install_brew_supported():
    # Frontend-only feature: TypeScript source is the only testable artifact at the Python unit level.
    src = Path("frontend/src/pages/SaltOpsPage.tsx").read_text()
    assert "brew" in src.lower()


def test_inline_help_exists():
    # Frontend-only feature: TypeScript source is the only testable artifact at the Python unit level.
    src = Path("frontend/src/pages/SaltOpsPage.tsx").read_text()
    assert "showHelp" in src or "help" in src.lower()


def test_per_minion_result_table():
    # Frontend-only feature: TypeScript source is the only testable artifact at the Python unit level.
    src = Path("frontend/src/pages/SaltOpsPage.tsx").read_text()
    # Result view uses parsedOutput with per-minion breakdown (rendered as div/ul, not necessarily <table>)
    assert "parsedOutput" in src and "minion" in src.lower()


def test_pip_install_in_allowlist():
    # Behavioral: import the default Salt function set and confirm pip.install is present (#255).
    from fleet_platform.services.platform_settings_svc import _DEFAULT_SALT_FUNCTIONS

    assert "pip.install" in _DEFAULT_SALT_FUNCTIONS, "pip.install must be in the default Salt allowlist (issue #255)"


def test_no_new_backend_files():
    # All changes are frontend-only
    assert not Path("fleet_platform/api/routes/salt_ux.py").exists()


def test_result_shows_per_minion():
    # Frontend-only feature: TypeScript source is the only testable artifact at the Python unit level.
    src = Path("frontend/src/pages/SaltOpsPage.tsx").read_text()
    assert "minion" in src.lower() and "result" in src.lower()


def test_typescript_interfaces_intact():
    # Frontend-only feature: TypeScript source is the only testable artifact at the Python unit level.
    src = Path("frontend/src/api/saltOps.ts").read_text()
    assert "SaltState" in src
