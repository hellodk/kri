"""Tests for Linux salt onedir air-gapped install wiring (#696).

These are structural/static tests — they verify that the playbook files,
role tasks, and defaults exist and reference the correct variables.  Live
execution validation requires a real Linux host and is documented in the
commit body.
"""

from pathlib import Path

import yaml

PLAYBOOKS = Path(__file__).resolve().parents[2] / "playbooks"
ROLE_TASKS = PLAYBOOKS / "roles/salt_master/tasks"
ROLE_DEFAULTS = PLAYBOOKS / "roles/salt_master/defaults/main.yml"


# ---------------------------------------------------------------------------
# Structural: new files exist
# ---------------------------------------------------------------------------


def test_install_linux_onedir_task_file_exists():
    f = ROLE_TASKS / "install_linux_onedir.yml"
    assert f.exists(), "install_linux_onedir.yml not found in role tasks"


def test_install_salt_master_linux_playbook_exists():
    f = PLAYBOOKS / "install_salt_master_linux.yml"
    assert f.exists(), "install_salt_master_linux.yml playbook not found"


# ---------------------------------------------------------------------------
# Defaults: new variables are declared
# ---------------------------------------------------------------------------


def _defaults() -> dict:
    return yaml.safe_load(ROLE_DEFAULTS.read_text()) or {}


def test_defaults_has_salt_linux_airgap():
    d = _defaults()
    assert "salt_linux_airgap" in d, "salt_linux_airgap not in defaults/main.yml"
    assert d["salt_linux_airgap"] is False, "salt_linux_airgap default must be False (opt-in)"


def test_defaults_has_salt_linux_arch():
    d = _defaults()
    assert "salt_linux_arch" in d, "salt_linux_arch not in defaults/main.yml"
    assert d["salt_linux_arch"] == "x86_64", "default arch must be x86_64"


def test_defaults_has_salt_linux_tarball_name():
    d = _defaults()
    assert "salt_linux_tarball_name" in d, "salt_linux_tarball_name not in defaults/main.yml"
    assert "salt_version" in d["salt_linux_tarball_name"], "tarball name must reference salt_version variable"
    assert "salt_linux_arch" in d["salt_linux_tarball_name"], "tarball name must reference salt_linux_arch variable"


def test_defaults_has_salt_linux_onedir_official_base():
    d = _defaults()
    assert "salt_linux_onedir_official_base" in d, "salt_linux_onedir_official_base not in defaults/main.yml"
    url = d["salt_linux_onedir_official_base"]
    assert "broadcom.com" in url or "saltproject" in url, f"official base URL should point to SaltProject: {url}"


# ---------------------------------------------------------------------------
# Role main.yml: onedir branch wired correctly
# ---------------------------------------------------------------------------


def _main_tasks_src() -> str:
    return (ROLE_TASKS / "main.yml").read_text()


def test_main_yml_references_install_linux_onedir():
    src = _main_tasks_src()
    assert "install_linux_onedir" in src, "main.yml must include install_linux_onedir.yml for air-gapped Linux"


def test_main_yml_onedir_conditional_on_airgap_flag():
    src = _main_tasks_src()
    assert "salt_linux_airgap" in src, "main.yml must gate onedir install on salt_linux_airgap flag"


# ---------------------------------------------------------------------------
# install_linux_onedir.yml: key task keywords present
# ---------------------------------------------------------------------------


def _onedir_src() -> str:
    return (ROLE_TASKS / "install_linux_onedir.yml").read_text()


def test_onedir_task_extracts_tarball():
    src = _onedir_src()
    # Air-gapped rewrite (#970/#973) extracts the bundled tarball via `tar -xJf`
    # in a shell task rather than the unarchive module.
    assert "tar -xJf" in src, "install_linux_onedir.yml must extract the tarball (tar -xJf)"


def test_onedir_task_creates_symlinks():
    src = _onedir_src()
    assert "salt-master" in src, "install_linux_onedir.yml must create salt-master symlink"
    assert "salt-api" in src, "install_linux_onedir.yml must create salt-api symlink"
    assert "salt-key" in src, "install_linux_onedir.yml must create salt-key symlink"


def test_onedir_task_copies_bundled_tarball():
    # #970/#973 made the Linux onedir install fully air-gapped: the pinned tarball
    # is bundled and copied to the target — no Artifactory/official-URL download.
    src = _onedir_src()
    assert "copy:" in src, "install_linux_onedir.yml must copy the bundled tarball to the target"


def test_onedir_task_has_local_bundle_source():
    src = _onedir_src()
    assert "salt_linux_tarball_local_path" in src, "install_linux_onedir.yml must use the local bundle path"


def test_onedir_task_is_airgapped_no_download():
    src = _onedir_src()
    # Air-gapped: no network-fetch modules in the install task (the word
    # "Artifactory" appears only in a comment explaining what is NOT done).
    assert "get_url" not in src, "install_linux_onedir.yml must not download (air-gapped)"
    assert "ansible.builtin.uri" not in src, "install_linux_onedir.yml must not fetch over HTTP (air-gapped)"


def test_onedir_task_verifies_checksum():
    src = _onedir_src()
    assert "sha256" in src.lower(), "install_linux_onedir.yml must verify the sha256 checksum before extract"


# ---------------------------------------------------------------------------
# install_salt_master_linux.yml: air-gapped pre-flight wired in
# ---------------------------------------------------------------------------


def _linux_playbook_src() -> str:
    return (PLAYBOOKS / "install_salt_master_linux.yml").read_text()


def test_linux_playbook_has_airgap_preflight():
    src = _linux_playbook_src()
    assert "salt_linux_airgap" in src, "install_salt_master_linux.yml must have a pre-flight check for air-gapped mode"


def test_linux_playbook_download_instructions_in_warning():
    src = _linux_playbook_src()
    assert "onedir" in src, "install_salt_master_linux.yml should mention 'onedir' in the air-gapped warning"
    assert "curl" in src or "download" in src.lower(), (
        "install_salt_master_linux.yml should include download instructions for the bundle"
    )
