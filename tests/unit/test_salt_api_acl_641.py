# tests/unit/test_salt_api_acl_641.py
"""Tests for #641: salt-api external_auth ACL parity with _DEFAULT_SALT_FUNCTIONS.

The bug: kri-master.conf.j2 only authorized test.ping + @wheel/@runner in the
external_auth ACL. Every local-client call (ps.kill_pid, service.stop, cmd.run,
state.apply, etc.) was auth-denied by salt-api on the native master. Docker mode
had no ACL so the bug was masked there.

These tests enforce that the template ACL and the app-side allowlist stay in
parity — if _DEFAULT_SALT_FUNCTIONS grows, the template must grow with it.
"""

import re
from pathlib import Path

from fleet_platform.services.platform_settings_svc import _DEFAULT_SALT_FUNCTIONS

# ---------------------------------------------------------------------------
# Paths — always relative to this file, never absolute
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATE = _REPO_ROOT / "playbooks" / "roles" / "salt_master" / "templates" / "kri-master.conf.j2"
_DOCKER_CONF = _REPO_ROOT / "deploy" / "salt-master.conf"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# @wheel and @runner entries are NOT local-client execution functions.
_WHEEL_RUNNER_PREFIXES = ("@wheel", "@runner")

_WHEEL_RUNNER_FUNCTIONS = frozenset(
    {
        "key.list_all",
        "key.accept",
        "key.reject",
        "key.delete",
        "manage.up",
        "manage.versions",
        "manage.status",
    }
)


def _extract_bare_function_strings(text: str) -> frozenset[str]:
    """Return the set of bare-string Salt function entries from a YAML/Jinja config.

    Matches lines of the form:
        - 'function.name'
    or
        - "function.name"

    and excludes @wheel / @runner block headers and their sub-entries (which are
    indented under the block key).  We detect sub-entries by checking whether the
    matched function looks like a known @wheel or @runner sub-function.
    """
    pattern = re.compile(r"^\s+-\s+['\"]([a-z_]+\.[a-z_]+)['\"]\s*$", re.MULTILINE)
    matches = pattern.findall(text)
    # Exclude sub-entries that belong to @wheel / @runner blocks
    return frozenset(m for m in matches if m not in _WHEEL_RUNNER_FUNCTIONS)


def _local_client_functions_from_default() -> frozenset[str]:
    """Return only the local-client (execution module) functions from the default set.

    @wheel and @runner entries in external_auth use different YAML block syntax;
    _DEFAULT_SALT_FUNCTIONS only contains execution-module functions, so no
    filtering is actually necessary — but we make this explicit for clarity.
    """
    return _DEFAULT_SALT_FUNCTIONS - _WHEEL_RUNNER_FUNCTIONS


# ---------------------------------------------------------------------------
# 1. Template file exists and is parseable as text
# ---------------------------------------------------------------------------


def test_template_exists():
    assert _TEMPLATE.exists(), f"Template not found: {_TEMPLATE}"


# ---------------------------------------------------------------------------
# 2. Parity: every local-client function in _DEFAULT_SALT_FUNCTIONS is present
#    in the kri-master.conf.j2 external_auth ACL.
#
#    This is the real security property: if the app allowlist grows but the
#    ACL does not, salt-api will deny the new function in production.
# ---------------------------------------------------------------------------


def test_template_acl_contains_all_default_salt_functions():
    text = _TEMPLATE.read_text()
    template_acl = _extract_bare_function_strings(text)
    local_client_funcs = _local_client_functions_from_default()
    missing = local_client_funcs - template_acl
    assert not missing, (
        f"Functions in _DEFAULT_SALT_FUNCTIONS that are MISSING from kri-master.conf.j2 ACL "
        f"(salt-api will deny these in production): {sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# 3. Specific functions kri dispatches via run_salt_cmd must be present
# ---------------------------------------------------------------------------

_CRITICAL_DISPATCH_FUNCTIONS = frozenset(
    {
        "ps.kill_pid",
        "service.stop",
        "service.disable",
        "state.apply",
        # cmd.run removed (#758): it grants arbitrary shell execution (RCE) on any
        # minion — equivalent to operator-level remote code execution.  kri has no
        # legitimate use-case for cmd.run; all operations use specific Salt modules.
        "ps.list_processes",
        "service.get_all",
    }
)

# Functions that MUST NOT appear in any Salt API ACL.
_DANGEROUS_FUNCTIONS = frozenset(
    {
        "cmd.run",
        "cmd.run_all",
        "cmd.shell",
        "cmd.exec_code",
    }
)


def test_template_acl_contains_critical_dispatch_functions():
    text = _TEMPLATE.read_text()
    template_acl = _extract_bare_function_strings(text)
    missing = _CRITICAL_DISPATCH_FUNCTIONS - template_acl
    assert not missing, f"Critical dispatch functions missing from kri-master.conf.j2 ACL: {sorted(missing)}"


def test_template_acl_does_not_contain_dangerous_functions():
    """cmd.run and equivalent RCE functions must NOT be in the ACL (#758)."""
    text = _TEMPLATE.read_text()
    template_acl = _extract_bare_function_strings(text)
    present = _DANGEROUS_FUNCTIONS & template_acl
    assert not present, (
        f"Dangerous functions found in kri-master.conf.j2 ACL — these grant "
        f"arbitrary shell execution on any minion (#758): {sorted(present)}"
    )


# ---------------------------------------------------------------------------
# 4. @wheel and @runner blocks are still present and correct
# ---------------------------------------------------------------------------


def test_template_preserves_wheel_block():
    text = _TEMPLATE.read_text()
    assert "'@wheel'" in text or '"@wheel"' in text, "@wheel block missing from template"
    for fn in ("key.list_all", "key.accept", "key.reject", "key.delete"):
        assert fn in text, f"@wheel function {fn!r} missing from template"


def test_template_preserves_runner_block():
    text = _TEMPLATE.read_text()
    assert "'@runner'" in text or '"@runner"' in text, "@runner block missing from template"
    for fn in ("manage.up", "manage.versions", "manage.status"):
        assert fn in text, f"@runner function {fn!r} missing from template"


# ---------------------------------------------------------------------------
# 5. Docker parity: deploy/salt-master.conf must have the same local-client ACL
# ---------------------------------------------------------------------------


def test_docker_conf_exists():
    assert _DOCKER_CONF.exists(), f"Docker salt-master config not found: {_DOCKER_CONF}"


def test_docker_conf_has_external_auth():
    text = _DOCKER_CONF.read_text()
    assert "external_auth:" in text, "deploy/salt-master.conf must contain external_auth: section for docker parity"


def test_docker_conf_acl_contains_all_default_salt_functions():
    text = _DOCKER_CONF.read_text()
    docker_acl = _extract_bare_function_strings(text)
    local_client_funcs = _local_client_functions_from_default()
    missing = local_client_funcs - docker_acl
    assert not missing, (
        f"Functions in _DEFAULT_SALT_FUNCTIONS missing from deploy/salt-master.conf ACL "
        f"(docker and native would behave differently): {sorted(missing)}"
    )


def test_docker_conf_contains_critical_dispatch_functions():
    text = _DOCKER_CONF.read_text()
    docker_acl = _extract_bare_function_strings(text)
    missing = _CRITICAL_DISPATCH_FUNCTIONS - docker_acl
    assert not missing, f"Critical dispatch functions missing from deploy/salt-master.conf ACL: {sorted(missing)}"


def test_docker_conf_does_not_contain_dangerous_functions():
    """cmd.run and equivalent RCE functions must NOT be in the docker ACL (#758)."""
    text = _DOCKER_CONF.read_text()
    docker_acl = _extract_bare_function_strings(text)
    present = _DANGEROUS_FUNCTIONS & docker_acl
    assert not present, (
        f"Dangerous functions found in deploy/salt-master.conf ACL — these grant "
        f"arbitrary shell execution on any minion (#758): {sorted(present)}"
    )


def test_default_salt_functions_does_not_contain_dangerous_functions():
    """_DEFAULT_SALT_FUNCTIONS must not include cmd.run or equivalent RCE functions (#758)."""
    present = _DANGEROUS_FUNCTIONS & _DEFAULT_SALT_FUNCTIONS
    assert not present, f"Dangerous functions found in _DEFAULT_SALT_FUNCTIONS — remove them (#758): {sorted(present)}"
