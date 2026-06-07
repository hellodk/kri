"""
tests/unit/test_cli_saltmaster_wrapper_561.py

#561 — Verify that scripts/kri cmd_saltmaster_install uses the shared
provision_master playbooks and that its post-install messaging directs
operators to the kri UI (Settings → Salt Masters) without referencing
retired .env.docker env-var hints.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPTS_KRI = Path(__file__).parents[2] / "scripts" / "kri"


def _script_text() -> str:
    return SCRIPTS_KRI.read_text(encoding="utf-8")


# ── playbook references ───────────────────────────────────────────────────────


def test_macos_playbook_referenced():
    """cmd_saltmaster_install invokes the shared macOS playbook."""
    assert "install_salt_master.yml" in _script_text(), (
        "scripts/kri must reference install_salt_master.yml (shared provision_master path)"
    )


def test_linux_playbook_referenced():
    """cmd_saltmaster_install invokes the shared Linux playbook."""
    assert "install_salt_master_linux.yml" in _script_text(), (
        "scripts/kri must reference install_salt_master_linux.yml (shared provision_master path)"
    )


# ── post-install messaging: UI-first, no stale env hints ─────────────────────


def test_next_steps_references_salt_masters_ui():
    """Post-install message directs operator to Settings → Salt Masters."""
    text = _script_text()
    assert "Salt Masters" in text, "Post-install 'Next steps' must reference 'Salt Masters' UI section"


def test_next_steps_no_salt_api_url_hint():
    """Post-install message does not reference SALT_API_URL env var hint."""
    # SALT_API_URL is still read by cmd_saltmaster_status, so we check only
    # the block that follows cmd_saltmaster_install success — i.e. the
    # "Next steps" section.  We look for SALT_API_URL inside the info/echo
    # lines that form that block.
    text = _script_text()
    # Locate "Next steps" block in cmd_saltmaster_install and inspect it.
    # The block ends at the next "else" (failure path) or closing "fi".
    lines = text.splitlines()
    in_next_steps = False
    for line in lines:
        stripped = line.strip()
        if "Next steps:" in stripped:
            in_next_steps = True
        if in_next_steps:
            # Stop at the failure branch or end of function
            if stripped.startswith("else") or stripped == "}":
                break
            assert "SALT_API_URL" not in line, f"Post-install Next steps must not reference SALT_API_URL: {line!r}"


def test_next_steps_no_salt_api_password_hint():
    """Post-install message does not reference SALT_API_PASSWORD env var hint."""
    text = _script_text()
    lines = text.splitlines()
    in_next_steps = False
    for line in lines:
        stripped = line.strip()
        if "Next steps:" in stripped:
            in_next_steps = True
        if in_next_steps:
            if stripped.startswith("else") or stripped == "}":
                break
            assert "SALT_API_PASSWORD" not in line, (
                f"Post-install Next steps must not reference SALT_API_PASSWORD: {line!r}"
            )


def test_next_steps_no_env_docker_salt_master_hint():
    """Post-install message does not reference SALT_MASTER env var hint."""
    text = _script_text()
    lines = text.splitlines()
    in_next_steps = False
    for line in lines:
        stripped = line.strip()
        if "Next steps:" in stripped:
            in_next_steps = True
        if in_next_steps:
            if stripped.startswith("else") or stripped == "}":
                break
            # Reject the env-var name SALT_MASTER as a hint in this block
            # (it is fine to mention "Salt Masters" as UI label)
            assert "SALT_MASTER=" not in line, (
                f"Post-install Next steps must not reference SALT_MASTER= env hint: {line!r}"
            )


# ── shell syntax ─────────────────────────────────────────────────────────────


def test_shell_syntax_ok():
    """bash -n scripts/kri must pass with exit code 0."""
    result = subprocess.run(
        ["bash", "-n", str(SCRIPTS_KRI)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"scripts/kri has shell syntax errors:\n{result.stderr}"
