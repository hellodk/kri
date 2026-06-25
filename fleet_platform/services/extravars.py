# fleet_platform/services/extravars.py
"""Sensitive extravars scrubbing.

Extracted from the original flat ``api/routes/ansible.py`` (#750) so the
ansible route package and the worker layer can share a single definition of
which extravar keys are sensitive and how to redact them before logging or
auditing.
"""

_SENSITIVE_EV_KEYS = frozenset(
    {
        "ansible_ssh_pass",
        "ansible_become_password",
        "ansible_become_pass",
        "ansible_password",
        "ansible_sudo_pass",
        "vault_password",
        "password",
        "secret",
        "token",
        "api_key",
    }
)


def _scrub_extravars(ev: dict | list | None) -> dict | list | None:
    """Recursively scrub sensitive keys from extravars (flat dict, nested dict, or list)."""
    if isinstance(ev, dict):
        return {k: "***" if k.lower() in _SENSITIVE_EV_KEYS else _scrub_extravars(v) for k, v in ev.items()}
    if isinstance(ev, list):
        return [_scrub_extravars(item) for item in ev]
    return ev
