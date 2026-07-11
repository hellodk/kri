"""Source-contract tests for issue #694 — bootstrap_node.yml hanging + broken checksum.

Verifies at the playbook file level (no live host needed) that:
1. The broken lookup('file')/lookup('pipe') checksum path is gone — it ran on
   the controller not the target and silently skipped verification.
2. The Check installed salt version task uses pkgutil (not salt-minion --version
   which boots the macOS onedir daemon and never returns).
3. The shasum -a 512 on-target verification task is still present (the real gate).

Roles-refactor Phase 3: this logic moved out of the bootstrap_node.yml monolith
into playbooks/roles/salt_minion/tasks/install_macos.yml, verbatim (the #694 fix
must be preserved exactly regardless of which file it lives in).
"""

from pathlib import Path

# Resolve relative to this test file so the test works from any cwd (source-contract
# pattern: Path(__file__) not an absolute path).
PLAYBOOK = Path(__file__).parent.parent.parent / "playbooks" / "roles" / "salt_minion" / "tasks" / "install_macos.yml"


def _content() -> str:
    return PLAYBOOK.read_text()


# ---------------------------------------------------------------------------
# Bug 2 — broken controller-side lookup checksum must be gone
# ---------------------------------------------------------------------------


def test_no_lookup_file_for_checksum():
    """lookup('file') on the controller cannot read a file downloaded to the target.

    The broken task used lookup('file', '/tmp/' + salt_checksum_filename) which
    resolves on the CONTROLLER, not the remote host — returns empty string and
    silently skips the checksum.  It must be gone.
    """
    content = _content()
    assert "lookup('file'" not in content, (
        "bootstrap_node.yml must not use lookup('file'...) for checksum verification — "
        "it runs on the controller, not the target, and silently skips the check"
    )


def test_no_lookup_pipe_for_checksum():
    """lookup('pipe') is equally broken — runs cat on the controller, not the target."""
    content = _content()
    assert "lookup('pipe'" not in content, "bootstrap_node.yml must not use lookup('pipe'...) for checksum verification"


# ---------------------------------------------------------------------------
# Bug 1 — version detection must not run the bare salt-minion binary
# ---------------------------------------------------------------------------


def test_check_installed_salt_version_uses_pkgutil():
    """The Check installed salt version task must use pkgutil, not salt-minion --version.

    Running the salt-minion binary on macOS onedir boots the daemon process and
    never reaches EOF — the task hangs for 300s until timeout.
    pkgutil --pkg-info reads the .pkg receipt and exits instantly.
    """
    content = _content()
    assert "pkgutil" in content, "bootstrap_node.yml must use pkgutil --pkg-info for salt version detection"


def test_check_installed_salt_version_task_no_bare_binary():
    """The Check installed salt version task block must not shell out to salt-minion --version."""
    content = _content()
    lines = content.splitlines()

    in_check_task = False
    for i, line in enumerate(lines):
        if "name: Check installed salt version" in line:
            in_check_task = True
        elif in_check_task:
            # The task ends at the next top-level task (another `- name:`)
            stripped = line.lstrip()
            if stripped.startswith("- name:") and "Check installed salt version" not in line:
                break
            # Within the task, the shell command must not be the raw binary path
            if "salt-minion --version" in line and "timeout" not in line:
                raise AssertionError(
                    f"Line {i + 1}: Check installed salt version task runs "
                    f"'salt-minion --version' without a guard — this hangs on macOS onedir. "
                    f"Use pkgutil --pkg-info instead."
                )


def test_confirm_installed_salt_version_no_bare_binary():
    """The Confirm installed salt version matches expected task must also not use bare binary."""
    content = _content()
    lines = content.splitlines()

    in_confirm_task = False
    for i, line in enumerate(lines):
        if "name: Confirm installed salt version matches expected" in line:
            in_confirm_task = True
        elif in_confirm_task:
            stripped = line.lstrip()
            if stripped.startswith("- name:") and "Confirm installed salt version" not in line:
                break
            if "salt-minion --version" in line and "timeout" not in line:
                raise AssertionError(
                    f"Line {i + 1}: Confirm installed salt version task runs "
                    f"'salt-minion --version' without a timeout guard — hangs risk. "
                    f"Use pkgutil --pkg-info instead."
                )


# ---------------------------------------------------------------------------
# Checksum verification still runs on-target (the real gate)
# ---------------------------------------------------------------------------


def test_shasum_verify_task_present():
    """The shasum -a 512 on-target verification task must still be present.

    This is the real checksum gate: it runs ON the target (correct), parses
    EXPECTED from the downloaded checksum file, computes ACTUAL from the pkg,
    and exit 1 on mismatch — aborting the bootstrap.
    """
    content = _content()
    assert "shasum -a 512" in content, (
        "bootstrap_node.yml must still contain the shasum -a 512 on-target "
        "verification task — removing it would leave the pkg unverified"
    )


def test_shasum_verify_exits_on_mismatch():
    """The shasum verify task must exit 1 on mismatch (not just print a warning)."""
    content = _content()
    assert "exit 1" in content, (
        "bootstrap_node.yml shasum verify task must 'exit 1' on checksum mismatch "
        "to abort the bootstrap rather than continuing with a corrupt pkg"
    )
