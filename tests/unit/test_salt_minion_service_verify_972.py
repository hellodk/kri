"""Issue #972 — salt-minion service verify must not use service_facts.

service_facts' launchd/BSD provider does not reliably populate
ansible_facts.services on macOS, raising "object of type 'dict' has no attribute
'services'" and failing bootstrap. The verify step must use a pgrep process check
that works on macOS + Linux.

Paths resolved via pathlib from this file (never absolute).
"""

from pathlib import Path

_SERVICE_YML = (
    Path(__file__).resolve().parents[2]
    / "playbooks"
    / "roles"
    / "salt_minion"
    / "tasks"
    / "service.yml"
)


def _src() -> str:
    return _SERVICE_YML.read_text()


def test_verify_does_not_use_service_facts():
    # Comments may explain *why not*; the executable module call must be gone.
    src = _src()
    assert "ansible.builtin.service_facts:" not in src
    assert "ansible_facts.services" not in src


def test_verify_uses_pgrep_with_retries():
    src = _src()
    assert 'pgrep -f "[s]alt-minion"' in src
    assert "until:" in src
    assert "retries:" in src


def test_verify_fails_clearly_when_not_running():
    src = _src()
    assert "ansible.builtin.fail:" in src
    assert "not running" in src
