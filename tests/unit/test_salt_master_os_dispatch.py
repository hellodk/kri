"""Tests for OS-aware salt_master role dispatch (#359)."""
from pathlib import Path

ROLE = Path("playbooks/roles/salt_master/tasks")


def test_os_install_files_exist():
    for f in ["install_macos.yml", "install_debian.yml", "install_redhat.yml"]:
        assert (ROLE / f).exists(), f"{f} must exist"


def test_service_files_exist():
    assert (ROLE / "service_macos.yml").exists()
    assert (ROLE / "service_systemd.yml").exists()


def test_main_dispatches_by_os():
    main = (ROLE / "main.yml").read_text()
    assert "_salt_os" in main
    assert "ansible_os_family" in main
    assert 'include_tasks: "install_{{ _salt_os }}.yml"' in main
    assert "unsupported" in main


def test_macos_uses_full_path_installer():
    assert "/usr/sbin/installer" in (ROLE / "install_macos.yml").read_text()


def test_debian_uses_apt():
    deb = (ROLE / "install_debian.yml").read_text()
    assert "apt" in deb and "salt-master" in deb


def test_redhat_uses_dnf():
    rh = (ROLE / "install_redhat.yml").read_text()
    assert "dnf" in rh or "yum" in rh
