"""Source-contract tests for #390: shared SecretInput — kills browser autofill."""

from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
FRONTEND_SRC = ROOT / "frontend" / "src"

# ---------------------------------------------------------------------------
# Files under test
# ---------------------------------------------------------------------------
SECRET_INPUT = (FRONTEND_SRC / "components" / "SecretInput.tsx").read_text()

# Files that must have been migrated away from raw type="password"
MIGRATED_FILES = [
    FRONTEND_SRC / "components" / "LLMEndpointForm.tsx",
    # GroupDetail.tsx no longer uses SecretInput (#1002): the inline SSH form was
    # replaced by a Credential picker; the credential's secret lives on the
    # Credentials page instead.
    FRONTEND_SRC / "pages" / "FleetDashboard.tsx",
    FRONTEND_SRC / "pages" / "SettingsPage.tsx",
]

# The login page is explicitly exempted — it is a real login form
LOGIN_PAGE = (FRONTEND_SRC / "pages" / "LoginPage.tsx").read_text()


# ---------------------------------------------------------------------------
# SecretInput.tsx — shape and anti-autofill attributes
# ---------------------------------------------------------------------------


def test_secret_input_file_exists():
    assert (FRONTEND_SRC / "components" / "SecretInput.tsx").exists()


def test_secret_input_autocomplete_new_password():
    assert 'autoComplete="new-password"' in SECRET_INPUT


def test_secret_input_data_lpignore():
    assert 'data-lpignore="true"' in SECRET_INPUT


def test_secret_input_data_1p_ignore():
    assert "data-1p-ignore" in SECRET_INPUT


def test_secret_input_reveal_toggle():
    # The component must switch between 'password' and 'text'
    assert "revealed" in SECRET_INPUT
    assert "'password'" in SECRET_INPUT or '"password"' in SECRET_INPUT
    assert "'text'" in SECRET_INPUT or '"text"' in SECRET_INPUT


def test_secret_input_uses_useId():
    assert "useId" in SECRET_INPUT


def test_secret_input_stable_name_prefix():
    assert "kri-secret-" in SECRET_INPUT


def test_secret_input_monospace_font():
    assert "font-mono" in SECRET_INPUT


def test_secret_input_exports_named_function():
    assert "export function SecretInput" in SECRET_INPUT


# ---------------------------------------------------------------------------
# Migration: no raw type="password" outside SecretInput and LoginPage
# ---------------------------------------------------------------------------


def test_no_raw_password_in_migrated_files():
    """Each migrated file must no longer contain type="password" literally."""
    for path in MIGRATED_FILES:
        src = path.read_text()
        assert 'type="password"' not in src, (
            f'{path.relative_to(ROOT)} still contains type="password" — migrate to <SecretInput>'
        )


def test_login_page_still_has_password_type():
    """LoginPage is explicitly exempted — it is a real login form."""
    # It uses a state-toggled password/text pattern, not type="password" directly
    # (it already has its own reveal toggle). Either form is acceptable.
    assert "password" in LOGIN_PAGE  # sanity: login page still deals with passwords


def test_migrated_files_import_secret_input():
    """Every migrated file must import SecretInput."""
    for path in MIGRATED_FILES:
        src = path.read_text()
        assert "SecretInput" in src, f"{path.relative_to(ROOT)} was migrated but does not import SecretInput"
