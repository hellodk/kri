# tests/unit/test_ansible_cfg_353.py
"""Tests for #353: playbooks/ansible.cfg — persistent Ansible config file.

TDD: these tests were written BEFORE the implementation.
"""

import configparser
from pathlib import Path

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent
_ANSIBLE_CFG = _REPO_ROOT / "playbooks" / "ansible.cfg"
_WORKER_SRC = (_REPO_ROOT / "fleet_platform" / "workers" / "playbook_tasks.py").read_text()


# ---------------------------------------------------------------------------
# 1. playbooks/ansible.cfg existence and parsability
# ---------------------------------------------------------------------------


def test_ansible_cfg_exists():
    assert _ANSIBLE_CFG.exists(), "playbooks/ansible.cfg must exist (created by #353)"


def test_ansible_cfg_parses():
    cfg = configparser.ConfigParser()
    read = cfg.read(str(_ANSIBLE_CFG))
    assert str(_ANSIBLE_CFG) in read, "configparser could not read playbooks/ansible.cfg"


# ---------------------------------------------------------------------------
# 2. Required [defaults] settings
# ---------------------------------------------------------------------------


def _parsed_cfg() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read(str(_ANSIBLE_CFG))
    return cfg


def test_retry_files_disabled():
    cfg = _parsed_cfg()
    val = cfg.get("defaults", "retry_files_enabled", fallback=None)
    assert val is not None, "[defaults] retry_files_enabled must be present"
    assert val.strip().lower() in ("false", "0", "no"), f"retry_files_enabled must be False, got {val!r}"


def test_forks_20():
    cfg = _parsed_cfg()
    val = cfg.get("defaults", "forks", fallback=None)
    assert val is not None, "[defaults] forks must be present"
    assert int(val.strip()) == 20, f"forks must be 20, got {val!r}"


def test_host_key_checking_false():
    cfg = _parsed_cfg()
    val = cfg.get("defaults", "host_key_checking", fallback=None)
    assert val is not None, "[defaults] host_key_checking must be present"
    assert val.strip().lower() in ("false", "0", "no"), f"host_key_checking must be False, got {val!r}"


# ---------------------------------------------------------------------------
# 3. Required [ssh_connection] settings
# ---------------------------------------------------------------------------


def test_pipelining_true():
    cfg = _parsed_cfg()
    val = cfg.get("ssh_connection", "pipelining", fallback=None)
    assert val is not None, "[ssh_connection] pipelining must be present"
    assert val.strip().lower() in ("true", "1", "yes"), f"pipelining must be True, got {val!r}"


def test_ssh_args_contains_user_known_hosts_dev_null():
    cfg = _parsed_cfg()
    val = cfg.get("ssh_connection", "ssh_args", fallback=None)
    assert val is not None, "[ssh_connection] ssh_args must be present"
    assert "UserKnownHostsFile=/dev/null" in val, f"ssh_args must contain UserKnownHostsFile=/dev/null, got {val!r}"


# ---------------------------------------------------------------------------
# 4. Source-contract tests on playbook_tasks.py
# ---------------------------------------------------------------------------


def test_ansible_config_env_var_present():
    """ANSIBLE_CONFIG env var must be set so the worker points at the cfg file."""
    assert '"ANSIBLE_CONFIG"' in _WORKER_SRC, "ANSIBLE_CONFIG must be in the envvars dict in playbook_tasks.py"


def test_ansible_host_key_checking_env_removed():
    """ANSIBLE_HOST_KEY_CHECKING moved to ansible.cfg — must not be in envvars."""
    assert '"ANSIBLE_HOST_KEY_CHECKING"' not in _WORKER_SRC, (
        "ANSIBLE_HOST_KEY_CHECKING has been moved to ansible.cfg and must be removed from envvars"
    )


def test_ansible_ssh_args_env_removed():
    """ANSIBLE_SSH_ARGS moved to ansible.cfg — must not be in envvars."""
    assert '"ANSIBLE_SSH_ARGS"' not in _WORKER_SRC, (
        "ANSIBLE_SSH_ARGS has been moved to ansible.cfg and must be removed from envvars"
    )


def test_ansible_timeout_env_removed():
    """ANSIBLE_TIMEOUT moved to ansible.cfg — must not be in envvars."""
    assert '"ANSIBLE_TIMEOUT"' not in _WORKER_SRC, (
        "ANSIBLE_TIMEOUT has been moved to ansible.cfg and must be removed from envvars"
    )


def test_ansible_ssh_retries_env_removed():
    """ANSIBLE_SSH_RETRIES moved to ansible.cfg — must not be in envvars."""
    assert '"ANSIBLE_SSH_RETRIES"' not in _WORKER_SRC, (
        "ANSIBLE_SSH_RETRIES has been moved to ansible.cfg and must be removed from envvars"
    )


def test_ansible_task_timeout_env_removed():
    """ANSIBLE_TASK_TIMEOUT moved to ansible.cfg — must not be in envvars."""
    assert '"ANSIBLE_TASK_TIMEOUT"' not in _WORKER_SRC, (
        "ANSIBLE_TASK_TIMEOUT has been moved to ansible.cfg and must be removed from envvars"
    )


def test_ansible_force_color_still_present():
    """ANSIBLE_FORCE_COLOR is dynamic/delivery-critical — must NOT be removed."""
    assert '"ANSIBLE_FORCE_COLOR": "1"' in _WORKER_SRC, (
        "ANSIBLE_FORCE_COLOR must remain in envvars (dynamic, no cfg equivalent)"
    )


def test_ansible_collections_path_still_present():
    """ANSIBLE_COLLECTIONS_PATH is path-dependent per source — must stay in envvars."""
    assert '"ANSIBLE_COLLECTIONS_PATH"' in _WORKER_SRC, (
        "ANSIBLE_COLLECTIONS_PATH must remain in envvars (per-source path)"
    )


def test_ansible_roles_path_still_present():
    """ANSIBLE_ROLES_PATH is path-dependent per source — must stay in envvars."""
    assert '"ANSIBLE_ROLES_PATH"' in _WORKER_SRC, "ANSIBLE_ROLES_PATH must remain in envvars (per-source path)"
