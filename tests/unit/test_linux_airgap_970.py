"""Contract tests for #970 — extend the kri air-gap to Linux salt + monitoring
installs.

Covers:
  - salt_minion install_debian.yml / install_redhat.yml no longer use get_url
    (they dispatch to the bundled onedir tarball install instead of apt/dnf repos).
  - salt_master install_linux_onedir.yml no longer uses get_url (bundled-copy only).
  - salt_master's salt_linux_tarball_name default now ends in .tar.xz (the real
    onedir artifact extension; .tar.gz 404s against packages.broadcom.com).
  - The bundled Linux tarballs (node_exporter, otelcol-contrib, salt onedir) and
    their checksum sidecars exist under playbooks/files/ (git-LFS).
  - The Linux salt onedir extraction uses `tar -xJf` (xz), never `-xzf` (gzip).

All paths are relative to the repository root, resolved via pathlib from this
file's location (never absolute), so the test works regardless of cwd.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYBOOKS_DIR = REPO_ROOT / "playbooks"
FILES_DIR = PLAYBOOKS_DIR / "files"

SALT_MASTER_DIR = PLAYBOOKS_DIR / "roles" / "salt_master"
SALT_MINION_DIR = PLAYBOOKS_DIR / "roles" / "salt_minion"

SALT_MASTER_DEFAULTS = SALT_MASTER_DIR / "defaults" / "main.yml"
SALT_MASTER_INSTALL_LINUX_ONEDIR = SALT_MASTER_DIR / "tasks" / "install_linux_onedir.yml"

SALT_MINION_INSTALL_DEBIAN = SALT_MINION_DIR / "tasks" / "install_debian.yml"
SALT_MINION_INSTALL_REDHAT = SALT_MINION_DIR / "tasks" / "install_redhat.yml"
SALT_MINION_INSTALL_LINUX_ONEDIR = SALT_MINION_DIR / "tasks" / "install_linux_onedir.yml"

NO_GET_URL_FILES = [
    SALT_MINION_INSTALL_DEBIAN,
    SALT_MINION_INSTALL_REDHAT,
    SALT_MASTER_INSTALL_LINUX_ONEDIR,
]

BUNDLED_LINUX_ARTIFACTS = [
    "node_exporter-1.8.2.linux-amd64.tar.gz",
    "node_exporter-1.8.2.linux-amd64.tar.gz.sha256",
    "otelcol-contrib_0.119.0_linux_amd64.tar.gz",
    "otelcol-contrib_0.119.0_linux_amd64.tar.gz.sha256",
    "salt-3007.14-onedir-linux-x86_64.tar.xz",
    "salt-3007.14-onedir-linux-x86_64.tar.xz.sha256",
]


def _load_tasks(path: Path) -> list[dict]:
    docs = yaml.safe_load(path.read_text())
    assert isinstance(docs, list), f"{path} did not parse to a list of tasks"
    return docs


def _all_task_dicts(tasks: list) -> list[dict]:
    """Flatten include_tasks/block-free task lists; these role files are flat
    lists of task dicts (no nested blocks today), so this is a light wrapper
    kept for readability rather than deep recursion."""
    return [t for t in tasks if isinstance(t, dict)]


class TestNoGetUrlInAirGappedInstalls:
    def test_no_files_missing(self):
        for path in NO_GET_URL_FILES:
            assert path.exists(), f"expected file not found: {path}"

    def test_salt_minion_install_debian_has_no_get_url(self):
        tasks = _load_tasks(SALT_MINION_INSTALL_DEBIAN)
        for task in _all_task_dicts(tasks):
            assert "get_url" not in task, (
                f"install_debian.yml must not use get_url (air-gap #970): {task}"
            )

    def test_salt_minion_install_redhat_has_no_get_url(self):
        tasks = _load_tasks(SALT_MINION_INSTALL_REDHAT)
        for task in _all_task_dicts(tasks):
            assert "get_url" not in task, (
                f"install_redhat.yml must not use get_url (air-gap #970): {task}"
            )

    def test_salt_master_install_linux_onedir_has_no_get_url(self):
        tasks = _load_tasks(SALT_MASTER_INSTALL_LINUX_ONEDIR)
        for task in _all_task_dicts(tasks):
            assert "get_url" not in task, (
                f"install_linux_onedir.yml must not use get_url (air-gap #970): {task}"
            )

    def test_no_get_url_string_anywhere_in_these_files(self):
        # Belt-and-braces: catch get_url used via a module FQCN
        # (ansible.builtin.get_url) that a dict-key check might miss.
        for path in NO_GET_URL_FILES:
            text = path.read_text()
            assert "get_url" not in text, f"found 'get_url' string in {path}"


class TestSaltLinuxTarballExtension:
    def test_salt_linux_tarball_name_ends_with_tar_xz(self):
        text = SALT_MASTER_DEFAULTS.read_text()
        docs = yaml.safe_load(text)
        tarball_name = docs["salt_linux_tarball_name"]
        assert tarball_name.endswith(".tar.xz"), (
            f"salt_linux_tarball_name must end with .tar.xz (real onedir "
            f"artifact extension), got: {tarball_name}"
        )
        assert not tarball_name.endswith(".tar.gz")


class TestBundledLinuxArtifactsExist:
    def test_bundled_linux_tarballs_and_checksums_exist(self):
        for name in BUNDLED_LINUX_ARTIFACTS:
            path = FILES_DIR / name
            assert path.exists(), f"bundled Linux artifact missing: {path}"

    def test_bundled_linux_tarballs_are_nonempty(self):
        for name in BUNDLED_LINUX_ARTIFACTS:
            path = FILES_DIR / name
            assert path.stat().st_size > 0, f"bundled artifact is empty: {path}"


class TestLinuxSaltExtractionUsesXz:
    def test_salt_master_extraction_uses_xJf_not_xzf(self):
        text = SALT_MASTER_INSTALL_LINUX_ONEDIR.read_text()
        assert "-xJf" in text, (
            "salt_master install_linux_onedir.yml must extract with tar -xJf (xz)"
        )
        assert "-xzf" not in text, (
            "salt_master install_linux_onedir.yml must not use -xzf (gzip) — "
            "the onedir artifact is .tar.xz"
        )

    def test_salt_minion_extraction_uses_xJf_not_xzf(self):
        assert SALT_MINION_INSTALL_LINUX_ONEDIR.exists()
        text = SALT_MINION_INSTALL_LINUX_ONEDIR.read_text()
        assert "-xJf" in text, (
            "salt_minion install_linux_onedir.yml must extract with tar -xJf (xz)"
        )
        assert "-xzf" not in text, (
            "salt_minion install_linux_onedir.yml must not use -xzf (gzip) — "
            "the onedir artifact is .tar.xz"
        )


class TestSaltMinionDispatchesToOnedirInstall:
    def test_install_debian_includes_onedir_task(self):
        tasks = _load_tasks(SALT_MINION_INSTALL_DEBIAN)
        included = [
            t.get("include_tasks")
            for t in _all_task_dicts(tasks)
            if "include_tasks" in t
        ]
        assert "install_linux_onedir.yml" in included, (
            "install_debian.yml must dispatch to install_linux_onedir.yml"
        )

    def test_install_redhat_includes_onedir_task(self):
        tasks = _load_tasks(SALT_MINION_INSTALL_REDHAT)
        included = [
            t.get("include_tasks")
            for t in _all_task_dicts(tasks)
            if "include_tasks" in t
        ]
        assert "install_linux_onedir.yml" in included, (
            "install_redhat.yml must dispatch to install_linux_onedir.yml"
        )
