"""
Tests for issue #545 — saltmaster install Linux support.

Validates:
- playbooks/install_salt_master_linux.yml exists with correct structure
- scripts/kri cmd_saltmaster_install no longer hardcodes ansible_user=dk
  and selects the Linux playbook for Linux targets
"""

from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Playbook structural tests
# ---------------------------------------------------------------------------


def test_linux_playbook_exists():
    """The Linux playbook file must exist."""
    path = Path("playbooks/install_salt_master_linux.yml")
    assert path.exists(), "playbooks/install_salt_master_linux.yml must exist"


def test_linux_playbook_is_valid_yaml():
    """The playbook must parse as valid YAML."""
    path = Path("playbooks/install_salt_master_linux.yml")
    content = path.read_text()
    plays = yaml.safe_load(content)
    assert isinstance(plays, list), "Playbook must be a YAML list of plays"
    assert len(plays) >= 2, "Must have at least a pre-flight play and an install play"


def test_linux_playbook_has_localhost_guard():
    """First play must validate that target_host is defined (localhost pre-flight)."""
    path = Path("playbooks/install_salt_master_linux.yml")
    plays = yaml.safe_load(path.read_text())
    preflight = plays[0]
    assert preflight["hosts"] == "localhost", "First play must run on localhost"
    task_names = [t.get("name", "") for t in preflight.get("tasks", [])]
    # At least one task must reference target_host validation
    assert any("target_host" in n.lower() or "fail" in n.lower() for n in task_names), (
        "Pre-flight play must contain a task that validates target_host"
    )


def test_linux_playbook_targets_target_host():
    """The install play must target the {{ target_host }} variable."""
    path = Path("playbooks/install_salt_master_linux.yml")
    plays = yaml.safe_load(path.read_text())
    # Find the install play (not localhost)
    install_plays = [p for p in plays if p.get("hosts") != "localhost"]
    assert len(install_plays) >= 1, "Must have at least one play that targets target_host"
    assert any("target_host" in str(p.get("hosts", "")) for p in install_plays), (
        "Install play must use {{ target_host }} as hosts"
    )


def test_linux_playbook_applies_salt_master_role():
    """The install play must apply the salt_master role."""
    path = Path("playbooks/install_salt_master_linux.yml")
    content = path.read_text()
    assert "salt_master" in content, "Playbook must reference the salt_master role"


def test_linux_playbook_uses_become():
    """The install play must use become: true (needs root for apt/yum install)."""
    path = Path("playbooks/install_salt_master_linux.yml")
    plays = yaml.safe_load(path.read_text())
    install_plays = [p for p in plays if p.get("hosts") != "localhost"]
    assert len(install_plays) >= 1
    install_play = install_plays[0]
    assert install_play.get("become") is True, (
        "Install play must set become: true for privileged Linux package installation"
    )


def test_linux_playbook_does_not_reference_macos_pkg():
    """The Linux playbook must NOT reference macOS-specific Salt artifacts.

    #883 installs the Linux onedir via the official SaltProject distribution at
    packages.broadcom.com/artifactory/saltproject-generic/onedir/. That host
    serves *all* platforms — including the Linux tarball
    (salt-<ver>-onedir-linux-<arch>.tar.gz) the playbook references — so a bare
    "broadcom" string is NOT a macOS marker. Guard instead against the genuinely
    macOS-only artifacts: the .pkg installer and any macos/darwin onedir build.
    """
    path = Path("playbooks/install_salt_master_linux.yml")
    content = path.read_text().lower()
    assert ".pkg" not in content, "Linux playbook must not reference macOS .pkg — Linux installs the onedir tarball"
    assert "arm64.pkg" not in content, "Linux playbook must not reference arm64.pkg"
    assert "onedir-macos" not in content, "Linux playbook must not reference the macOS onedir build"
    assert "onedir-darwin" not in content, "Linux playbook must not reference the darwin onedir build"


def test_linux_playbook_does_not_reference_launchd():
    """The Linux playbook must NOT use launchd (macOS service manager)."""
    path = Path("playbooks/install_salt_master_linux.yml")
    content = path.read_text()
    assert "launchd" not in content, "Linux playbook must not reference launchd — Linux uses systemd"


def test_linux_playbook_accepts_ansible_user_var():
    """The playbook must accept ansible_user as an extra-var (not hardcoded)."""
    path = Path("playbooks/install_salt_master_linux.yml")
    content = path.read_text()
    # ansible_user should appear as a variable reference, not hardcoded to 'dk'
    assert "ansible_user" in content, "Playbook must reference ansible_user variable"
    # Must NOT hardcode 'dk' as a literal username value (default is ok in var default)
    # The key assertion: the play's vars section should not set ansible_user: dk literally
    plays = yaml.safe_load(content)
    install_plays = [p for p in plays if p.get("hosts") != "localhost"]
    for play in install_plays:
        play_vars = play.get("vars", {})
        # ansible_user may have a default but should not be hardcoded as plain 'dk'
        # It must be expressed as a Jinja2 default expression, not a bare string 'dk'
        ansible_user_val = play_vars.get("ansible_user", "")
        is_jinja_default = "| default(" in str(ansible_user_val)
        is_jinja_ref = "{{ ansible_user" in str(ansible_user_val)
        is_absent = ansible_user_val == ""
        assert is_jinja_default or is_jinja_ref or is_absent, (
            f"ansible_user in play vars must use a Jinja2 default, not be hardcoded. Got: {ansible_user_val!r}"
        )


def test_linux_playbook_accepts_kri_salt_api_password():
    """The playbook must accept kri_salt_api_password as an extra-var."""
    path = Path("playbooks/install_salt_master_linux.yml")
    content = path.read_text()
    assert "kri_salt_api_password" in content, "Playbook must reference kri_salt_api_password variable"


# ---------------------------------------------------------------------------
# scripts/kri behavioural assertions (source-text checks)
# ---------------------------------------------------------------------------


def test_kri_script_cmd_saltmaster_install_does_not_hardcode_dk():
    """cmd_saltmaster_install must not hardcode ansible_user=dk."""
    script = Path("scripts/kri").read_text()
    # Find the cmd_saltmaster_install function block
    start = script.find("cmd_saltmaster_install()")
    assert start != -1, "cmd_saltmaster_install function must exist in scripts/kri"
    # Extract just the function (up to the next top-level function)
    func_block = script[start : start + 3000]  # generous slice
    # The literal string 'ansible_user=dk' (hardcoded) must not appear
    assert "ansible_user=dk" not in func_block, (
        "cmd_saltmaster_install must not hardcode -e ansible_user=dk; it must prompt for / accept the SSH user"
    )


def test_kri_script_references_linux_playbook():
    """scripts/kri must reference install_salt_master_linux.yml for Linux targets."""
    script = Path("scripts/kri").read_text()
    assert "install_salt_master_linux.yml" in script, (
        "scripts/kri must reference install_salt_master_linux.yml for Linux install path"
    )


def test_kri_script_has_os_detection_or_flag():
    """scripts/kri must have logic to distinguish macOS vs Linux targets."""
    script = Path("scripts/kri").read_text()
    start = script.find("cmd_saltmaster_install()")
    assert start != -1
    func_block = script[start : start + 4000]
    # Must contain either a --linux flag check or uname detection
    has_linux_flag = "--linux" in func_block
    has_uname = "uname" in func_block
    assert has_linux_flag or has_uname, (
        "cmd_saltmaster_install must detect or accept a flag to distinguish macOS vs Linux targets"
    )


def test_kri_script_next_steps_updated():
    """Post-install next steps must reference HTTPS salt-api and kri UI, not legacy .env.docker."""
    script = Path("scripts/kri").read_text()
    start = script.find("cmd_saltmaster_install()")
    assert start != -1
    func_block = script[start : start + 4000]
    # Must mention https (TLS) for salt-api
    assert "https" in func_block.lower() or "8080" in func_block, (
        "Next steps hint must reference salt-api URL (https or port 8080)"
    )
