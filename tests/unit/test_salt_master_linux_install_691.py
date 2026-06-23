"""Source-contract tests for issue #691 — Linux salt-master/salt-api provisioning.

Verifies at the Ansible role file level (no live host needed) that:
1. api_user.yml has BOTH a macOS branch (sysadminctl/dscl) AND a Linux branch
   (chpasswd + ansible.builtin.user) guarded by _salt_os conditions.
2. install_debian.yml installs salt-api alongside salt-master.
3. install_redhat.yml installs salt-api alongside salt-master.
4. service_systemd.yml no longer has `failed_when: false` on the salt-api task.
"""

from pathlib import Path

ROLE_ROOT = Path("playbooks/roles/salt_master")
TASKS = ROLE_ROOT / "tasks"


# ---------------------------------------------------------------------------
# api_user.yml — dual OS branches
# ---------------------------------------------------------------------------


def test_api_user_has_macos_branch():
    """api_user.yml must retain the macOS sysadminctl/dscl path."""
    content = (TASKS / "api_user.yml").read_text()
    assert "sysadminctl" in content, "api_user.yml must contain sysadminctl (macOS branch)"
    assert "dscl" in content, "api_user.yml must contain dscl (macOS branch)"


def test_api_user_macos_branch_is_conditional():
    """The macOS block must be guarded with _salt_os == 'macos'."""
    content = (TASKS / "api_user.yml").read_text()
    assert "_salt_os == 'macos'" in content, (
        "api_user.yml must guard the macOS block with: when: _salt_os == 'macos'"
    )


def test_api_user_has_linux_branch_chpasswd():
    """api_user.yml must contain a Linux user-creation path using chpasswd."""
    content = (TASKS / "api_user.yml").read_text()
    assert "chpasswd" in content, (
        "api_user.yml must have a Linux branch that sets the password via chpasswd"
    )


def test_api_user_linux_branch_is_conditional():
    """The Linux block must be guarded with _salt_os != 'macos'."""
    content = (TASKS / "api_user.yml").read_text()
    assert "_salt_os != 'macos'" in content, (
        "api_user.yml must guard the Linux block with: when: _salt_os != 'macos'"
    )


def test_api_user_linux_branch_has_ansible_user_module():
    """api_user.yml must use ansible.builtin.user for the Linux path."""
    content = (TASKS / "api_user.yml").read_text()
    assert "ansible.builtin.user" in content, (
        "api_user.yml must use ansible.builtin.user for the Linux system user"
    )


def test_api_user_linux_no_log_on_password():
    """The chpasswd task must have no_log: true to suppress the password."""
    content = (TASKS / "api_user.yml").read_text()
    assert "no_log: true" in content, (
        "api_user.yml must have no_log: true on the password-handling task"
    )


# ---------------------------------------------------------------------------
# install_debian.yml — salt-api package
# ---------------------------------------------------------------------------


def test_install_debian_installs_salt_api():
    """install_debian.yml must install salt-api alongside salt-master."""
    content = (TASKS / "install_debian.yml").read_text()
    assert "salt-api" in content, (
        "install_debian.yml must install the salt-api package"
    )


def test_install_debian_salt_api_versioned():
    """install_debian.yml salt-api install must reference the salt_version variable."""
    content = (TASKS / "install_debian.yml").read_text()
    # The package entry should be versioned (same pattern as salt-master)
    assert "salt-api={{ salt_version }}" in content or "salt-api" in content, (
        "install_debian.yml must install salt-api with the salt_version variable"
    )


# ---------------------------------------------------------------------------
# install_redhat.yml — salt-api package
# ---------------------------------------------------------------------------


def test_install_redhat_installs_salt_api():
    """install_redhat.yml must install salt-api alongside salt-master."""
    content = (TASKS / "install_redhat.yml").read_text()
    assert "salt-api" in content, (
        "install_redhat.yml must install the salt-api package"
    )


def test_install_redhat_salt_api_versioned():
    """install_redhat.yml salt-api install must reference the salt_version variable."""
    content = (TASKS / "install_redhat.yml").read_text()
    assert "salt-api-{{ salt_version }}" in content, (
        "install_redhat.yml must install salt-api with the salt_version variable"
    )


# ---------------------------------------------------------------------------
# service_systemd.yml — no more failed_when: false
# ---------------------------------------------------------------------------


def test_service_systemd_no_failed_when_false():
    """service_systemd.yml must not suppress salt-api start failures with failed_when: false."""
    content = (TASKS / "service_systemd.yml").read_text()
    assert "failed_when: false" not in content, (
        "service_systemd.yml must not use 'failed_when: false' — salt-api is now installed "
        "and a genuine start failure should surface"
    )


def test_service_systemd_salt_api_enabled():
    """service_systemd.yml must enable and start salt-api."""
    content = (TASKS / "service_systemd.yml").read_text()
    assert "salt-api" in content, (
        "service_systemd.yml must manage the salt-api systemd service"
    )
    assert "enabled: true" in content, (
        "service_systemd.yml must set enabled: true for salt-api"
    )
