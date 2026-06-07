"""Tests for salt-api TLS + scoped external_auth ACL (issue #535, epic #537).

These tests verify the Ansible role templates and task file at the source level —
no host or salt daemon needed. They check:
  - salt-api.conf.j2 enables TLS (disable_ssl: false, ssl_crt/ssl_key present)
  - kri-master.conf.j2 ACL is scoped: no '.*', no bare '@runner'/'@wheel'
  - kri-master.conf.j2 ACL contains the specific keys kri needs
  - tasks/api_tls.yml exists and generates the cert idempotently
  - No private key material committed in the role
"""

from pathlib import Path

ROLE_ROOT = Path("playbooks/roles/salt_master")
TEMPLATES = ROLE_ROOT / "templates"
TASKS = ROLE_ROOT / "tasks"
DEFAULTS = ROLE_ROOT / "defaults" / "main.yml"


# ---------------------------------------------------------------------------
# salt-api.conf.j2 — TLS config
# ---------------------------------------------------------------------------


def test_salt_api_conf_disables_ssl_is_false():
    """disable_ssl must be false — TLS is now enabled at the service."""
    content = (TEMPLATES / "salt-api.conf.j2").read_text()
    assert "disable_ssl: false" in content, "salt-api.conf.j2 must have 'disable_ssl: false'"


def test_salt_api_conf_no_disable_ssl_true():
    """The old 'disable_ssl: true' must no longer appear."""
    content = (TEMPLATES / "salt-api.conf.j2").read_text()
    assert "disable_ssl: true" not in content, "salt-api.conf.j2 must not have 'disable_ssl: true'"


def test_salt_api_conf_has_ssl_crt_var():
    """ssl_crt must reference the Jinja2 variable."""
    content = (TEMPLATES / "salt-api.conf.j2").read_text()
    assert "ssl_crt:" in content and "salt_api_ssl_crt" in content, (
        "salt-api.conf.j2 must have 'ssl_crt: {{ salt_api_ssl_crt }}'"
    )


def test_salt_api_conf_has_ssl_key_var():
    """ssl_key must reference the Jinja2 variable."""
    content = (TEMPLATES / "salt-api.conf.j2").read_text()
    assert "ssl_key:" in content and "salt_api_ssl_key" in content, (
        "salt-api.conf.j2 must have 'ssl_key: {{ salt_api_ssl_key }}'"
    )


# ---------------------------------------------------------------------------
# kri-master.conf.j2 — external_auth ACL
# ---------------------------------------------------------------------------


def test_kri_master_conf_no_wildcard_acl():
    """'.*' (all-function wildcard) must not appear in non-comment ACL lines."""
    content = (TEMPLATES / "kri-master.conf.j2").read_text()
    # Strip comment lines before checking — the comment may legitimately say '.*'
    # as documentation of what was removed; we only care about live config lines.
    non_comment_lines = [line for line in content.splitlines() if not line.strip().startswith("#")]
    non_comment = "\n".join(non_comment_lines)
    assert "'.*'" not in non_comment and '".*"' not in non_comment, (
        "kri-master.conf.j2 must not contain wildcard '.*' in external_auth (non-comment lines)"
    )


def test_kri_master_conf_no_bare_runner():
    """Bare '@runner' (grants all runners) must not appear — only specific runners."""
    content = (TEMPLATES / "kri-master.conf.j2").read_text()
    # A bare '@runner' entry as a list item (starts with '-') is the problem.
    # The scoped form uses '@runner': followed by a sub-list, which is fine.
    lines = content.splitlines()
    for line in lines:
        stripped = line.strip()
        # Match list items that are exactly '- '@runner'' or '- "@runner"'
        if stripped in ("- '@runner'", '- "@runner"'):
            raise AssertionError(f"kri-master.conf.j2 must not contain bare '@runner' list item: {line!r}")


def test_kri_master_conf_no_bare_wheel():
    """Bare '@wheel' (grants all wheel functions) must not appear."""
    content = (TEMPLATES / "kri-master.conf.j2").read_text()
    lines = content.splitlines()
    for line in lines:
        stripped = line.strip()
        if stripped in ("- '@wheel'", '- "@wheel"'):
            raise AssertionError(f"kri-master.conf.j2 must not contain bare '@wheel' list item: {line!r}")


def test_kri_master_conf_has_key_list_all():
    """key.list_all must be in the scoped wheel ACL."""
    content = (TEMPLATES / "kri-master.conf.j2").read_text()
    assert "key.list_all" in content, "kri-master.conf.j2 must include 'key.list_all' in wheel ACL"


def test_kri_master_conf_has_key_accept():
    """key.accept must be in the scoped wheel ACL."""
    content = (TEMPLATES / "kri-master.conf.j2").read_text()
    assert "key.accept" in content, "kri-master.conf.j2 must include 'key.accept' in wheel ACL"


def test_kri_master_conf_has_manage_up():
    """manage.up must be in the scoped runner ACL."""
    content = (TEMPLATES / "kri-master.conf.j2").read_text()
    assert "manage.up" in content, "kri-master.conf.j2 must include 'manage.up' in runner ACL"


# ---------------------------------------------------------------------------
# defaults/main.yml — SSL path vars present
# ---------------------------------------------------------------------------


def test_defaults_has_salt_api_ssl_crt():
    """defaults/main.yml must define salt_api_ssl_crt."""
    content = DEFAULTS.read_text()
    assert "salt_api_ssl_crt:" in content, "defaults/main.yml must define salt_api_ssl_crt"


def test_defaults_has_salt_api_ssl_key():
    """defaults/main.yml must define salt_api_ssl_key."""
    content = DEFAULTS.read_text()
    assert "salt_api_ssl_key:" in content, "defaults/main.yml must define salt_api_ssl_key"


# ---------------------------------------------------------------------------
# tasks/api_tls.yml — task file exists and is idempotent
# ---------------------------------------------------------------------------


def test_api_tls_task_file_exists():
    """tasks/api_tls.yml must exist."""
    assert (TASKS / "api_tls.yml").exists(), "tasks/api_tls.yml must exist"


def test_api_tls_uses_creates_for_idempotency():
    """The openssl command must use 'creates:' so it runs only once."""
    content = (TASKS / "api_tls.yml").read_text()
    assert "creates:" in content, "tasks/api_tls.yml must use 'creates:' to make cert generation idempotent"


def test_api_tls_notifies_restart_salt_api():
    """api_tls.yml must notify the 'Restart salt-api' handler on cert creation."""
    content = (TASKS / "api_tls.yml").read_text()
    assert "Restart salt-api" in content, "tasks/api_tls.yml must notify 'Restart salt-api' handler"


def test_api_tls_wired_into_main():
    """tasks/main.yml must import api_tls before the service tasks."""
    content = (TASKS / "main.yml").read_text()
    assert "api_tls.yml" in content, "tasks/main.yml must import_tasks api_tls.yml"
    # api_tls must appear before service_macos / service_systemd
    tls_pos = content.index("api_tls.yml")
    svc_pos = content.index("service_macos.yml")
    assert tls_pos < svc_pos, "api_tls.yml must be imported before the service tasks in main.yml"


# ---------------------------------------------------------------------------
# Security: no private key material committed in the role
# ---------------------------------------------------------------------------


def test_no_private_key_material_in_role():
    """No file in the role must contain a PEM private key header."""
    forbidden = "BEGIN PRIVATE" + " KEY"  # split to avoid pre-push secret scan
    forbidden_rsa = "BEGIN RSA PRIVATE" + " KEY"  # split to avoid pre-push secret scan
    for path in ROLE_ROOT.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(errors="replace")
        except Exception:
            continue
        assert forbidden not in text, f"Private key material found in {path} — do not commit keys to git"
        assert forbidden_rsa not in text, f"RSA private key material found in {path} — do not commit keys to git"


def test_no_key_file_committed_in_role():
    """No .key file must exist inside the role directory."""
    key_files = list(ROLE_ROOT.rglob("*.key"))
    assert key_files == [], f"Key files found committed in role: {key_files} — remove them"
