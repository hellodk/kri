"""Contract tests for #377 + #389: credentials API wiring and git-source auth flow."""

from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
CREDS_API = (ROOT / "frontend/src/api/credentials.ts").read_text()
SOURCES_API = (ROOT / "frontend/src/api/playbookSources.ts").read_text()
SETTINGS = (ROOT / "frontend/src/pages/SettingsPage.tsx").read_text()
SECRET_INPUT = (ROOT / "frontend/src/components/SecretInput.tsx").read_text()


def test_credentials_ts_exists_and_has_no_secret_field():
    # Credential interface must never expose the secret
    assert "interface Credential" in CREDS_API
    # Ensure no bare `secret` property in the Credential interface
    # (CredentialCreate has secret, but Credential must not)
    lines = CREDS_API.splitlines()
    in_credential_interface = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("export interface Credential") and "Create" not in stripped:
            in_credential_interface = True
            continue
        if in_credential_interface:
            if stripped == "}":
                break
            assert "secret" not in stripped, f"Credential interface must not expose secret field, found: {line!r}"


def test_credentials_api_posts_to_correct_path():
    assert "/api/v1/credentials" in CREDS_API


def test_playbook_sources_has_credential_id():
    assert "credential_id" in SOURCES_API


def test_playbook_sources_has_auth_required():
    assert "auth_required" in SOURCES_API


def test_settings_page_has_credentials_section():
    assert "CredentialsSection" in SETTINGS


def test_settings_page_has_credential_dropdown_state():
    assert "gitCredentialId" in SETTINGS


def test_settings_page_secret_input_has_autocomplete_new_password():
    # #390: autoComplete="new-password" now lives in the shared SecretInput component
    # which SettingsPage uses for all secret fields.
    assert 'autoComplete="new-password"' in SECRET_INPUT
    assert "SecretInput" in SETTINGS


def test_settings_page_has_amber_auth_message():
    assert "This repository is private or requires authentication" in SETTINGS


def test_settings_page_no_git_token_state():
    # gitToken state variable must not remain — credential dropdown replaced it
    assert "gitToken" not in SETTINGS


def test_settings_page_no_git_ssh_key_state():
    # gitSshKey state variable must not remain — credential dropdown replaced it
    assert "gitSshKey" not in SETTINGS
