"""Source-contract tests for issue #695 — configurable Linux salt repo URLs.

Verifies at the Ansible role file level (no live host needed) that:
1. install_debian.yml contains NO literal packages.broadcom.com URLs (all via vars).
2. install_redhat.yml contains NO literal packages.broadcom.com URLs (all via vars).
3. defaults/main.yml defines all four repo vars.
4. The default values in defaults/main.yml still point at the upstream Broadcom URLs.
"""

from pathlib import Path

ROLE_ROOT = Path(__file__).parent.parent.parent / "playbooks" / "roles" / "salt_master"
TASKS = ROLE_ROOT / "tasks"
DEFAULTS = ROLE_ROOT / "defaults" / "main.yml"

BROADCOM_HOST = "packages.broadcom.com"

DEB_REPO_DEFAULT = "https://packages.broadcom.com/artifactory/saltproject-deb/"
DEB_GPG_DEFAULT = "https://packages.broadcom.com/artifactory/api/security/keypair/SaltProjectKey/public"
RPM_REPO_DEFAULT = "https://packages.broadcom.com/artifactory/saltproject-rpm/"
RPM_GPG_DEFAULT = "https://packages.broadcom.com/artifactory/api/security/keypair/SaltProjectKey/public"


# ---------------------------------------------------------------------------
# install_debian.yml — no literal broadcom URLs
# ---------------------------------------------------------------------------


def test_install_debian_no_literal_broadcom_url():
    """install_debian.yml must contain no hardcoded packages.broadcom.com URLs."""
    content = (TASKS / "install_debian.yml").read_text()
    assert BROADCOM_HOST not in content, (
        "install_debian.yml must not contain any literal packages.broadcom.com URL — "
        "all repo/GPG URLs must be referenced via Ansible variables"
    )


def test_install_debian_uses_deb_gpg_url_var():
    """install_debian.yml must reference salt_deb_gpg_url for the GPG key download."""
    content = (TASKS / "install_debian.yml").read_text()
    assert "salt_deb_gpg_url" in content, (
        "install_debian.yml must use '{{ salt_deb_gpg_url }}' for the get_url task"
    )


def test_install_debian_uses_deb_repo_url_var():
    """install_debian.yml must reference salt_deb_repo_url for the apt repository."""
    content = (TASKS / "install_debian.yml").read_text()
    assert "salt_deb_repo_url" in content, (
        "install_debian.yml must use '{{ salt_deb_repo_url }}' in the apt_repository task"
    )


# ---------------------------------------------------------------------------
# install_redhat.yml — no literal broadcom URLs
# ---------------------------------------------------------------------------


def test_install_redhat_no_literal_broadcom_url():
    """install_redhat.yml must contain no hardcoded packages.broadcom.com URLs."""
    content = (TASKS / "install_redhat.yml").read_text()
    assert BROADCOM_HOST not in content, (
        "install_redhat.yml must not contain any literal packages.broadcom.com URL — "
        "all repo/GPG URLs must be referenced via Ansible variables"
    )


def test_install_redhat_uses_rpm_repo_baseurl_var():
    """install_redhat.yml must reference salt_rpm_repo_baseurl for the dnf repo."""
    content = (TASKS / "install_redhat.yml").read_text()
    assert "salt_rpm_repo_baseurl" in content, (
        "install_redhat.yml must use '{{ salt_rpm_repo_baseurl }}' in the yum_repository task"
    )


def test_install_redhat_uses_rpm_gpg_url_var():
    """install_redhat.yml must reference salt_rpm_gpg_url for the GPG key."""
    content = (TASKS / "install_redhat.yml").read_text()
    assert "salt_rpm_gpg_url" in content, (
        "install_redhat.yml must use '{{ salt_rpm_gpg_url }}' in the yum_repository task"
    )


# ---------------------------------------------------------------------------
# defaults/main.yml — four vars defined with correct broadcom defaults
# ---------------------------------------------------------------------------


def test_defaults_defines_salt_deb_repo_url():
    """defaults/main.yml must define salt_deb_repo_url."""
    content = DEFAULTS.read_text()
    assert "salt_deb_repo_url:" in content, (
        "defaults/main.yml must define salt_deb_repo_url"
    )


def test_defaults_defines_salt_deb_gpg_url():
    """defaults/main.yml must define salt_deb_gpg_url."""
    content = DEFAULTS.read_text()
    assert "salt_deb_gpg_url:" in content, (
        "defaults/main.yml must define salt_deb_gpg_url"
    )


def test_defaults_defines_salt_rpm_repo_baseurl():
    """defaults/main.yml must define salt_rpm_repo_baseurl."""
    content = DEFAULTS.read_text()
    assert "salt_rpm_repo_baseurl:" in content, (
        "defaults/main.yml must define salt_rpm_repo_baseurl"
    )


def test_defaults_defines_salt_rpm_gpg_url():
    """defaults/main.yml must define salt_rpm_gpg_url."""
    content = DEFAULTS.read_text()
    assert "salt_rpm_gpg_url:" in content, (
        "defaults/main.yml must define salt_rpm_gpg_url"
    )


def test_defaults_deb_repo_url_points_to_broadcom():
    """salt_deb_repo_url default must equal the upstream Broadcom deb repo URL."""
    content = DEFAULTS.read_text()
    assert DEB_REPO_DEFAULT in content, (
        f"defaults/main.yml salt_deb_repo_url default must be '{DEB_REPO_DEFAULT}'"
    )


def test_defaults_deb_gpg_url_points_to_broadcom():
    """salt_deb_gpg_url default must equal the upstream Broadcom GPG key URL."""
    content = DEFAULTS.read_text()
    assert DEB_GPG_DEFAULT in content, (
        f"defaults/main.yml salt_deb_gpg_url default must be '{DEB_GPG_DEFAULT}'"
    )


def test_defaults_rpm_repo_baseurl_points_to_broadcom():
    """salt_rpm_repo_baseurl default must equal the upstream Broadcom rpm repo URL."""
    content = DEFAULTS.read_text()
    assert RPM_REPO_DEFAULT in content, (
        f"defaults/main.yml salt_rpm_repo_baseurl default must be '{RPM_REPO_DEFAULT}'"
    )


def test_defaults_rpm_gpg_url_points_to_broadcom():
    """salt_rpm_gpg_url default must equal the upstream Broadcom GPG key URL."""
    content = DEFAULTS.read_text()
    assert RPM_GPG_DEFAULT in content, (
        f"defaults/main.yml salt_rpm_gpg_url default must be '{RPM_GPG_DEFAULT}'"
    )
