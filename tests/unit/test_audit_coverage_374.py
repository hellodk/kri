"""Source-contract tests for #374: audit coverage.

Each parametrized case reads the source module text and asserts:
  1. Every expected action string literal is present.
  2. The count of audit() or AuditEvent( invocations is >= expected_calls.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Root of the fleet_platform package (two levels up from tests/unit/)
_ROOT = Path(__file__).parent.parent.parent / "fleet_platform"


def _src(rel: str) -> str:
    return (_ROOT / rel).read_text()


# ---------------------------------------------------------------------------
# (module_rel_path, [action_strings], min_audit_calls)
# ---------------------------------------------------------------------------
_CASES: list[tuple[str, list[str], int]] = [
    # P0 — security-critical
    (
        "api/routes/group_secrets.py",
        ["group_secret.upsert", "group_secret.delete"],
        2,
    ),
    (
        "api/routes/node_secrets.py",
        ["node_secret.upsert", "node_secret.delete"],
        2,
    ),
    (
        "api/routes/salt_keys.py",
        ["salt_key.accept", "salt_key.reject", "salt_key.delete"],
        3,
    ),
    (
        "api/routes/platform_settings.py",
        ["platform_settings.update"],
        1,
    ),
    (
        "api/routes/ansible.py",
        [
            "node.bootstrap.request",
            "node.bootstrap.cancel",
            "playbook.run",
            "playbook_source.create",
            "playbook_source.delete",
            "playbook_source.bulk_import",
            "playbook_source.sync",
            "playbook_file.update",
        ],
        8,
    ),
    (
        "api/routes/salt_ops.py",
        ["salt.state.apply", "salt.cmd.run"],
        2,
    ),
    (
        "api/routes/llm.py",
        ["llm_endpoint.create", "llm_endpoint.update", "llm_endpoint.delete"],
        3,
    ),
    # P1 — ops-critical
    (
        "api/routes/security.py",
        ["security_scan.trigger", "security_scan.trigger_fleet"],
        2,
    ),
    (
        "api/routes/mobileconfig.py",
        [
            "mobileconfig.profile.create",
            "mobileconfig.profile.delete",
            "mobileconfig.profile.assign_group",
            "mobileconfig.profile.deploy",
        ],
        4,
    ),
    (
        "api/routes/provisioning.py",
        ["provisioning_profile.upload", "provisioning_profile.delete"],
        2,
    ),
    (
        "api/routes/alerts.py",
        ["alert_rule.create", "alert_rule.delete", "webhook.create", "webhook.delete"],
        4,
    ),
    (
        "api/routes/vnc.py",
        ["vnc.session.start"],
        1,
    ),
    # P2 — config changes
    (
        "api/routes/ios_tracking.py",
        ["ios_cert.create", "ios_cert.delete", "ios_jenkins_agent.upsert"],
        3,
    ),
    (
        "workers/security_tasks.py",
        ["security_scan.complete"],
        1,
    ),
    (
        "workers/mobileconfig_tasks.py",
        ["mobileconfig.deploy.complete"],
        1,
    ),
    (
        "api/routes/auth.py",
        ["auth.logout"],
        1,
    ),
    (
        "api/routes/oidc.py",
        ["auth.oidc_login"],
        1,
    ),
]


@pytest.mark.parametrize("rel_path,actions,min_calls", _CASES, ids=[c[0] for c in _CASES])
def test_audit_strings_present(rel_path: str, actions: list[str], min_calls: int) -> None:
    src = _src(rel_path)
    for action in actions:
        assert action in src, f"{rel_path}: action string '{action}' not found — audit() call missing"


@pytest.mark.parametrize("rel_path,actions,min_calls", _CASES, ids=[c[0] for c in _CASES])
def test_audit_call_count(rel_path: str, actions: list[str], min_calls: int) -> None:
    src = _src(rel_path)
    # Count both async audit() calls and sync AuditEvent( constructions
    call_count = len(re.findall(r"audit\(|AuditEvent\(", src))
    assert call_count >= min_calls, (
        f"{rel_path}: expected at least {min_calls} audit/AuditEvent call(s), found {call_count}"
    )
