"""Unit tests for fleet_platform.services.git_auth — TDD first pass."""

import os
import stat
import subprocess

from fleet_platform.services.git_auth import (
    AUTH_MARKERS,
    UNREACHABLE_MARKERS,
    classify_git_error,
    git_auth_env,
    redact_secrets,
)

# ---------------------------------------------------------------------------
# classify_git_error
# ---------------------------------------------------------------------------


class TestClassifyGitError:
    def test_auth_required_for_each_auth_marker(self):
        for marker in AUTH_MARKERS:
            result = classify_git_error(f"Some output: {marker} — bad creds")
            assert result == "auth_required", f"Expected auth_required for marker: {marker!r}"

    def test_auth_required_case_insensitive(self):
        assert classify_git_error("Could Not Read Username for the repo") == "auth_required"
        assert classify_git_error("AUTHENTICATION FAILED") == "auth_required"

    def test_unreachable_for_each_unreachable_marker(self):
        for marker in UNREACHABLE_MARKERS:
            result = classify_git_error(f"fatal: {marker}")
            assert result == "unreachable", f"Expected unreachable for marker: {marker!r}"

    def test_not_found(self):
        assert classify_git_error("ERROR: Repository not found.") == "not_found"
        assert classify_git_error("fatal: repository 'https://github.com/x/y' not found") == "not_found"

    def test_other_for_gibberish(self):
        assert classify_git_error("some random unknown error xyz") == "other"
        assert classify_git_error("") == "other"

    def test_auth_required_takes_priority_over_not_found(self):
        # "authentication failed" + "not found" in same string → auth wins
        result = classify_git_error("authentication failed: repository not found")
        assert result == "auth_required"


# ---------------------------------------------------------------------------
# redact_secrets
# ---------------------------------------------------------------------------


class TestRedactSecrets:
    def test_redacts_single_secret(self):
        result = redact_secrets("clone https://ghp_abc123@github.com", ["ghp_abc123"])
        assert "ghp_abc123" not in result
        assert "***" in result

    def test_redacts_multiple_secrets(self):
        result = redact_secrets("token=secret1 key=secret2", ["secret1", "secret2"])
        assert "secret1" not in result
        assert "secret2" not in result

    def test_handles_none_entries(self):
        # None / empty strings in the list should be silently skipped
        result = redact_secrets("hello world", [None, "", "world"])
        assert "world" not in result
        assert "hello" in result

    def test_no_secrets(self):
        result = redact_secrets("nothing here", [])
        assert result == "nothing here"

    def test_multiple_occurrences_all_redacted(self):
        result = redact_secrets("abc abc abc", ["abc"])
        assert "abc" not in result
        assert result.count("***") == 3


# ---------------------------------------------------------------------------
# git_auth_env
# ---------------------------------------------------------------------------


class TestGitAuthEnv:
    def test_always_sets_terminal_prompt_to_zero(self):
        with git_auth_env() as env:
            assert env.get("GIT_TERMINAL_PROMPT") == "0"

    def test_no_creds_sets_ssh_batch_mode(self):
        with git_auth_env() as env:
            ssh_cmd = env.get("GIT_SSH_COMMAND", "")
            assert "BatchMode=yes" in ssh_cmd

    def test_token_creates_askpass_script(self):
        with git_auth_env(token="mytoken") as env:
            askpass = env.get("GIT_ASKPASS")
            assert askpass is not None
            assert os.path.isfile(askpass)

    def test_token_askpass_is_executable(self):
        with git_auth_env(token="mytoken") as env:
            askpass = env.get("GIT_ASKPASS")
            assert os.access(askpass, os.X_OK)

    def test_token_askpass_username_returns_x_access_token(self):
        with git_auth_env(token="mytoken123") as env:
            askpass = env.get("GIT_ASKPASS")
            result = subprocess.run(
                [askpass, "Username for https://github.com"],
                env=env,
                capture_output=True,
                text=True,
            )
            assert result.stdout.strip() == "x-access-token"

    def test_token_askpass_password_returns_token(self):
        with git_auth_env(token="mytoken123") as env:
            askpass = env.get("GIT_ASKPASS")
            result = subprocess.run(
                [askpass, "Password for https://github.com"],
                env=env,
                capture_output=True,
                text=True,
            )
            assert result.stdout.strip() == "mytoken123"

    def test_token_not_in_git_ssh_command(self):
        with git_auth_env(token="supersecret") as env:
            ssh_cmd = env.get("GIT_SSH_COMMAND", "")
            assert "supersecret" not in ssh_cmd

    def test_token_only_in_kri_git_pass(self):
        with git_auth_env(token="supersecret") as env:
            for key, val in env.items():
                if key == "KRI_GIT_PASS":
                    continue
                assert "supersecret" not in (val or ""), f"Token leaked into env var {key!r}"

    def test_ssh_key_creates_key_file(self):
        fake_key = "-----BEGIN EC" + " PRIVATE KEY-----\nfakekey\n-----END EC" + " PRIVATE KEY-----\n"
        with git_auth_env(ssh_key=fake_key) as env:
            ssh_cmd = env.get("GIT_SSH_COMMAND", "")
            # extract -i argument
            parts = ssh_cmd.split()
            idx = parts.index("-i")
            key_file = parts[idx + 1]
            assert os.path.isfile(key_file)

    def test_ssh_key_file_mode_0600(self):
        fake_key = "-----BEGIN EC" + " PRIVATE KEY-----\nfakekey\n-----END EC" + " PRIVATE KEY-----\n"
        with git_auth_env(ssh_key=fake_key) as env:
            ssh_cmd = env.get("GIT_SSH_COMMAND", "")
            parts = ssh_cmd.split()
            idx = parts.index("-i")
            key_file = parts[idx + 1]
            mode = oct(stat.S_IMODE(os.stat(key_file).st_mode))
            assert mode == oct(0o600), f"Expected 0600, got {mode}"

    def test_ssh_key_path_in_git_ssh_command(self):
        fake_key = "-----BEGIN EC" + " PRIVATE KEY-----\nfakekey\n-----END EC" + " PRIVATE KEY-----\n"
        with git_auth_env(ssh_key=fake_key) as env:
            ssh_cmd = env.get("GIT_SSH_COMMAND", "")
            assert "-i" in ssh_cmd
            assert "BatchMode=yes" in ssh_cmd

    def test_temp_files_removed_after_context(self):
        fake_key = "-----BEGIN EC" + " PRIVATE KEY-----\nfakekey\n-----END EC" + " PRIVATE KEY-----\n"
        key_file_path = None
        askpass_path = None
        with git_auth_env(token="tok", ssh_key=fake_key) as env:
            ssh_cmd = env.get("GIT_SSH_COMMAND", "")
            parts = ssh_cmd.split()
            idx = parts.index("-i")
            key_file_path = parts[idx + 1]
            askpass_path = env.get("GIT_ASKPASS")

        assert key_file_path is not None
        assert not os.path.exists(key_file_path), "SSH key temp file not cleaned up"
        assert askpass_path is not None
        assert not os.path.exists(askpass_path), "GIT_ASKPASS temp file not cleaned up"
