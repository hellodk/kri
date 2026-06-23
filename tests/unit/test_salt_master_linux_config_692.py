"""Source-contract tests for issue #692 — Linux salt_master role blockers.

Verifies at the Ansible role file level (no live host needed) that:
1. configure.yml has NO unconditional 'group: wheel' — every group line uses
   the OS-conditional expression ('wheel' if ansible_system == 'Darwin' else 'root').
2. handlers/main.yml retains the macOS launchctl path (regression guard).
3. handlers/main.yml has a Linux systemd path for salt-master and salt-api.
"""

from pathlib import Path

ROLE_ROOT = Path("playbooks/roles/salt_master")
TASKS = ROLE_ROOT / "tasks"
HANDLERS = ROLE_ROOT / "handlers"


# ---------------------------------------------------------------------------
# configure.yml — no unconditional group: wheel
# ---------------------------------------------------------------------------


def test_configure_no_bare_group_wheel():
    """configure.yml must not contain a bare 'group: wheel' line.

    Every group assignment must be the OS-conditional:
        group: "{{ 'wheel' if ansible_system == 'Darwin' else 'root' }}"
    A bare 'group: wheel' would break on Debian/Ubuntu where the wheel group
    does not exist.
    """
    content = (TASKS / "configure.yml").read_text()
    for lineno, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if stripped == "group: wheel":
            raise AssertionError(
                f"configure.yml line {lineno}: unconditional 'group: wheel' found. "
                "Replace with: group: \"{{ 'wheel' if ansible_system == 'Darwin' else 'root' }}\""
            )


def test_configure_group_uses_os_conditional():
    """configure.yml must use the Darwin/root conditional for every group assignment."""
    content = (TASKS / "configure.yml").read_text()
    conditional = "'wheel' if ansible_system == 'Darwin' else 'root'"
    assert conditional in content, (
        "configure.yml must use the OS-conditional group expression: "
        f"group: \"{{{{ {conditional} }}}}\""
    )


def test_configure_all_five_group_lines_are_conditional():
    """All 5 group: lines in configure.yml must be OS-conditional, not bare wheel."""
    content = (TASKS / "configure.yml").read_text()
    conditional = "'wheel' if ansible_system == 'Darwin' else 'root'"
    conditional_count = content.count(conditional)
    # 5 tasks: /etc/salt dir, /etc/salt/master.d dir, kri.conf, salt-api.conf, log dir
    assert conditional_count >= 5, (
        f"configure.yml must have at least 5 OS-conditional group lines, found {conditional_count}"
    )


# ---------------------------------------------------------------------------
# handlers/main.yml — macOS path retained (regression guard)
# ---------------------------------------------------------------------------


def test_handlers_retain_macos_launchctl():
    """handlers/main.yml must still contain the launchctl macOS path."""
    content = (HANDLERS / "main.yml").read_text()
    assert "launchctl" in content, (
        "handlers/main.yml must retain the macOS launchctl handler path"
    )


def test_handlers_macos_guarded_by_darwin_when():
    """The launchctl blocks must be guarded by when: ansible_system == 'Darwin'."""
    content = (HANDLERS / "main.yml").read_text()
    assert "ansible_system == 'Darwin'" in content, (
        "handlers/main.yml must guard launchctl tasks with: when: ansible_system == 'Darwin'"
    )


# ---------------------------------------------------------------------------
# handlers/main.yml — Linux systemd path added
# ---------------------------------------------------------------------------


def test_handlers_have_systemd_salt_master():
    """handlers/main.yml must include a systemd handler for salt-master."""
    content = (HANDLERS / "main.yml").read_text()
    assert "ansible.builtin.systemd" in content or "ansible.builtin.systemd:" in content, (
        "handlers/main.yml must use ansible.builtin.systemd for the Linux path"
    )
    assert "salt-master" in content, (
        "handlers/main.yml must reference the salt-master service in a systemd handler"
    )


def test_handlers_have_systemd_salt_api():
    """handlers/main.yml must include a systemd handler for salt-api."""
    content = (HANDLERS / "main.yml").read_text()
    assert "salt-api" in content, (
        "handlers/main.yml must reference the salt-api service"
    )
    # Confirm there is a systemd block that covers salt-api (Linux path)
    assert "ansible_system != 'Darwin'" in content, (
        "handlers/main.yml must guard the systemd tasks with: when: ansible_system != 'Darwin'"
    )


def test_handlers_linux_guarded_by_not_darwin():
    """All systemd handlers must be guarded with when: ansible_system != 'Darwin'."""
    content = (HANDLERS / "main.yml").read_text()
    assert "ansible_system != 'Darwin'" in content, (
        "handlers/main.yml must guard systemd tasks with: when: ansible_system != 'Darwin'"
    )


def test_handlers_listen_strings_present():
    """handlers/main.yml must use listen: so a single notify triggers both OS paths."""
    content = (HANDLERS / "main.yml").read_text()
    assert "listen: Restart salt-master" in content, (
        "handlers/main.yml must use 'listen: Restart salt-master' on both macOS and Linux handlers"
    )
    assert "listen: Restart salt-api" in content, (
        "handlers/main.yml must use 'listen: Restart salt-api' on both macOS and Linux handlers"
    )
    assert "listen: Reload and start salt-master" in content, (
        "handlers/main.yml must use 'listen: Reload and start salt-master'"
    )
    assert "listen: Reload and start salt-api" in content, (
        "handlers/main.yml must use 'listen: Reload and start salt-api'"
    )
