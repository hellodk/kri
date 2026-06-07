"""Issue #595: salt_master role must enable netapi clients.

Salt 3006+ disables all netapi clients by default — salt-api returns
`400 Client disabled: 'runner'` for every /run call even with valid PAM auth.
kri uses the local, runner and wheel clients via salt-api, so the master config
template must enable them. Source-contract test: parse the Jinja2 template.
"""

import re
from pathlib import Path

TEMPLATE = (
    Path(__file__).parent.parent.parent / "playbooks" / "roles" / "salt_master" / "templates" / "kri-master.conf.j2"
)
_SOURCE = TEMPLATE.read_text()

REQUIRED_CLIENTS = ["local", "local_async", "runner", "wheel"]


def test_template_exists():
    assert TEMPLATE.exists(), f"{TEMPLATE} must exist"


def test_netapi_enable_clients_key_present():
    assert "netapi_enable_clients" in _SOURCE, (
        "kri-master.conf.j2 must set netapi_enable_clients — Salt 3006+ disables "
        "all netapi clients by default, breaking salt-api /run for kri."
    )


def _netapi_block() -> str:
    """Return the netapi_enable_clients YAML block (key + following list items)."""
    m = re.search(r"netapi_enable_clients:\s*\n((?:\s*-\s*\w+\s*\n?)+)", _SOURCE)
    assert m, "netapi_enable_clients must be a YAML list (key followed by '- client' items)"
    return m.group(1)


def test_required_clients_enabled():
    block = _netapi_block()
    listed = set(re.findall(r"-\s*(\w+)", block))
    missing = [c for c in REQUIRED_CLIENTS if c not in listed]
    assert not missing, f"netapi_enable_clients missing required clients: {missing} (found {sorted(listed)})"


def test_no_overbroad_clients():
    """Least privilege: only the clients kri actually uses — no wildcards / extras."""
    block = _netapi_block()
    listed = set(re.findall(r"-\s*(\w+)", block))
    extra = listed - set(REQUIRED_CLIENTS)
    assert not extra, f"netapi_enable_clients has clients kri does not use: {sorted(extra)}"
