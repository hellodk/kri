"""Issue #966 — salt-minion macOS install must be air-gapped (copy bundled pkg).

The env is air-gapped, so bootstrap must not download the salt pkg at runtime.
roles/salt_minion/tasks/install_macos.yml must copy the pkg + checksum bundled
under playbooks/files/ onto the target and validate against the bundled .sha512 —
no get_url, no download-URL resolution. Pinned version stays 3007.14 (matches the
master; bumping is a separate, riskier change).

Paths resolved via pathlib from this file (never absolute).
"""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INSTALL_MACOS = _REPO_ROOT / "playbooks" / "roles" / "salt_minion" / "tasks" / "install_macos.yml"
_FILES_DIR = _REPO_ROOT / "playbooks" / "files"


def _src() -> str:
    return _INSTALL_MACOS.read_text()


def test_no_get_url_download_in_macos_install():
    src = _src()
    assert "get_url" not in src, (
        "Air-gapped install must not download the salt pkg — use copy of the bundled "
        "pkg from playbooks/files/ instead."
    )


def test_no_dead_download_url_resolution():
    src = _src()
    # The download-URL set_fact (salt_pkg_url / Artifactory / official base) is dead
    # once nothing downloads.
    assert "salt_pkg_url" not in src
    assert "salt_pkg_official_base" not in src
    assert "artifactory_binary_url" not in src


def test_copies_bundled_pkg_and_checksum_from_files_dir():
    src = _src()
    assert "ansible.builtin.copy" in src, "must copy the bundled pkg/checksum"
    assert "files/{{ salt_pkg_filename }}" in src
    assert "files/{{ salt_checksum_filename }}" in src


def test_checksum_validation_retained():
    src = _src()
    # The bundled checksum is still validated against the copied pkg before install.
    assert "shasum -a 512" in src
    assert "CHECKSUM MISMATCH" in src


def test_bundled_arm64_pkg_and_checksum_present():
    assert (_FILES_DIR / "salt-3007.14-py3-arm64.pkg").exists()
    assert (_FILES_DIR / "salt-3007.14-py3-arm64.pkg.sha512").exists()
