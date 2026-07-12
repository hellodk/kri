"""Issue #982 — SSH keepalive so transient blips don't drop bootstraps.

A bootstrap failed mid-play with 'ssh: connect ... port 22: Connection timed out'
then passed on re-run. ServerAliveInterval keepalive is added to the play-level
ansible_ssh_common_args (which overrides ssh_args) in every SSH playbook, and to
ansible.cfg ssh_args.
"""

from pathlib import Path

_PB = Path(__file__).resolve().parents[2] / "playbooks"

_KEEPALIVE = "ServerAliveInterval=15"


def test_bootstrap_plays_have_keepalive():
    src = (_PB / "bootstrap_node.yml").read_text()
    # Both plays' ansible_ssh_common_args carry the keepalive.
    assert src.count(_KEEPALIVE) >= 2
    assert "ServerAliveCountMax=4" in src


def test_reconfigure_playbook_has_keepalive():
    src = (_PB / "reconfigure_minion_masters.yml").read_text()
    assert _KEEPALIVE in src


def test_ansible_cfg_ssh_args_has_keepalive():
    src = (_PB / "ansible.cfg").read_text()
    assert _KEEPALIVE in src
