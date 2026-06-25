"""Unit tests for git source credential wiring — TDD first pass (#377 + #389)."""

import inspect
import pathlib

from fleet_platform.schemas.playbook import (
    PlaybookSourceValidateRequest,
    PlaybookSourceValidateResponse,
)

# ---------------------------------------------------------------------------
# Schema additions
# ---------------------------------------------------------------------------


class TestPlaybookSourceValidateRequestSchema:
    def test_has_credential_id_field(self):
        fields = PlaybookSourceValidateRequest.model_fields
        assert "credential_id" in fields, "PlaybookSourceValidateRequest must have credential_id field"

    def test_credential_id_defaults_to_none(self):
        obj = PlaybookSourceValidateRequest(type="git", url="https://github.com/x/y")
        assert obj.credential_id is None


class TestPlaybookSourceValidateResponseSchema:
    def test_has_auth_required_field(self):
        fields = PlaybookSourceValidateResponse.model_fields
        assert "auth_required" in fields, "PlaybookSourceValidateResponse must have auth_required field"

    def test_auth_required_defaults_false(self):
        obj = PlaybookSourceValidateResponse(valid=True)
        assert obj.auth_required is False

    def test_has_error_kind_field(self):
        fields = PlaybookSourceValidateResponse.model_fields
        assert "error_kind" in fields, "PlaybookSourceValidateResponse must have error_kind field"

    def test_error_kind_defaults_none(self):
        obj = PlaybookSourceValidateResponse(valid=True)
        assert obj.error_kind is None


# ---------------------------------------------------------------------------
# No token-in-URL pattern in ansible.py
# ---------------------------------------------------------------------------


class TestNoTokenInURL:
    # #750: ansible.py is now the api/routes/ansible/ package (git-source handling
    # lives in sources.py). Read the whole package so these guards still apply.
    @staticmethod
    def _ansible_src() -> str:
        pkg = pathlib.Path("fleet_platform/api/routes/ansible")
        return "\n".join(p.read_text() for p in sorted(pkg.glob("*.py")))

    def test_ansible_py_has_no_token_url_injection(self):
        src = self._ansible_src()
        # Old pattern that injects token directly into URL string
        bad_pattern = 'f"{scheme_match.group(1)}{payload.token}@'
        assert bad_pattern not in src, "ansible package still injects token into URL — remove token-in-URL block"

    def test_ansible_py_uses_git_auth_env(self):
        src = self._ansible_src()
        assert "git_auth_env" in src, "ansible package must use git_auth_env from fleet_platform.services.git_auth"

    def test_ansible_py_uses_classify_git_error(self):
        src = self._ansible_src()
        assert "classify_git_error" in src, (
            "ansible package must use classify_git_error from fleet_platform.services.git_auth"
        )


# ---------------------------------------------------------------------------
# playbook_sources function signatures
# ---------------------------------------------------------------------------


class TestPlaybookSourcesSignatures:
    def test_clone_git_source_accepts_token_and_ssh_key(self):
        from fleet_platform.services.playbook_sources import _clone_git_source

        sig = inspect.signature(_clone_git_source)
        params = sig.parameters
        assert "token" in params, "_clone_git_source must accept token kwarg"
        assert "ssh_key" in params, "_clone_git_source must accept ssh_key kwarg"

    def test_pull_git_source_accepts_token_and_ssh_key(self):
        from fleet_platform.services.playbook_sources import _pull_git_source

        sig = inspect.signature(_pull_git_source)
        params = sig.parameters
        assert "token" in params, "_pull_git_source must accept token kwarg"
        assert "ssh_key" in params, "_pull_git_source must accept ssh_key kwarg"


# ---------------------------------------------------------------------------
# PlaybookSourceRequest has credential_id
# ---------------------------------------------------------------------------


class TestPlaybookSourceRequestSchema:
    def test_has_credential_id(self):
        from fleet_platform.schemas.playbook import PlaybookSourceRequest

        fields = PlaybookSourceRequest.model_fields
        assert "credential_id" in fields, "PlaybookSourceRequest must have credential_id field"
